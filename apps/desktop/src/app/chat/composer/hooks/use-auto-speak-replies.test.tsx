import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { atom } from 'nanostores'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { assistantTextPart, type ChatMessage, chatMessageText } from '@/lib/chat-messages'
import { clearSpokenRepliesForTests, markAssistantIdSpoken, resolveSpokenReply } from '@/lib/spoken-reply'
import { playSpeechText } from '@/lib/voice-playback'
import { $voicePlayback, setVoicePlaybackState } from '@/store/voice-playback'
import {
  $autoSpeakReplies,
  $ttsConclusionGraceMs,
  $ttsConclusionOnly
} from '@/store/voice-prefs'

import { ComposerScopeProvider, MAIN_COMPOSER_SCOPE } from '../scope'

import { useAutoSpeakReplies } from './use-auto-speak-replies'

vi.mock('@/lib/voice-playback', () => ({
  playSpeechText: vi.fn()
}))

// ownsAmbientCue talks to window.hermesDesktop (undefined in vitest) which makes
// the claim a real async hop. Stub it so the conclusion-only timer test can
// trust that the speak branch fires synchronously after the timer elapses.
vi.mock('@/store/ambient', () => ({
  ownsAmbientCue: vi.fn(async () => true)
}))

const SESSION_ID = 'session-under-test'
const IDLE_STATE = { audioElement: null, messageId: null, sequence: 0, source: null, status: 'idle' as const }

function assistantMessage(id: string, text: string): ChatMessage {
  return { id, parts: [assistantTextPart(text)], role: 'assistant' }
}

// #93515 — Edge TTS has no chunked-PCM API, so the WS attempt in
// playSpeechText's fallback ladder settles 'fallback' before any audio plays
// and the client retries over the POST endpoint. While that POST round-trip
// is in flight, the backend can rewrite the just-completed reply's renderer
// id (`assistant-stream-*`) to its durable id. The issue claims
// `resolveSpokenReply()` fails to follow that rewrite and the reply gets
// spoken a second time once `$voicePlayback` goes idle.
describe('useAutoSpeakReplies — Edge TTS fallback chain (#93515)', () => {
  afterEach(() => {
    cleanup()
    clearSpokenRepliesForTests()
    $autoSpeakReplies.set(false)
    setVoicePlaybackState({ ...IDLE_STATE })
    vi.clearAllMocks()
  })

  it('does not re-speak the reply once playback goes idle after an id rewrite mid-fallback', async () => {
    $autoSpeakReplies.set(true)

    const $messages = atom<ChatMessage[]>([])

    // The exact pendingReply/markSpoken contract use-composer-voice.ts wires
    // up for this hook, backed by the real ordinal-anchored dedupe.
    const pendingReply = () => {
      const messages = $messages.get()
      const last = messages.findLast(m => m.role === 'assistant' && !m.hidden)
      const spoken = resolveSpokenReply(SESSION_ID, messages)

      if (!last || last.id === spoken?.id) {
        return null
      }

      return { id: last.id, pending: Boolean(last.pending), text: chatMessageText(last) }
    }

    const markSpoken = () => {
      const messages = $messages.get()
      const last = messages.findLast(m => m.role === 'assistant' && !m.hidden)

      if (last) {
        markAssistantIdSpoken(SESSION_ID, messages, last.id)
      }
    }

    let settleFallback: (() => void) | null = null

    vi.mocked(playSpeechText).mockImplementation(async () => {
      setVoicePlaybackState({
        audioElement: null,
        messageId: 'assistant-stream-1',
        sequence: 0,
        source: 'read-aloud',
        status: 'preparing'
      })

      // Holds mid-ladder — the WS-fallback-then-POST round trip the issue
      // describes — until the test rewrites the message id underneath it.
      await new Promise<void>(resolve => {
        settleFallback = resolve
      })

      $messages.set([assistantMessage('durable-42', 'hello there')])

      setVoicePlaybackState({
        audioElement: null,
        messageId: 'durable-42',
        sequence: 0,
        source: 'read-aloud',
        status: 'idle'
      })

      return true
    })

    renderHook(
      () =>
        useAutoSpeakReplies({
          conversationActive: false,
          failureLabel: 'read-aloud failed',
          markSpoken,
          pendingReply,
          sessionId: SESSION_ID
        }),
      {
        wrapper: ({ children }) => (
          <ComposerScopeProvider value={{ ...MAIN_COMPOSER_SCOPE, $messages }}>{children}</ComposerScopeProvider>
        )
      }
    )

    act(() => {
      $messages.set([assistantMessage('assistant-stream-1', 'hello there')])
    })

    await waitFor(() => expect(playSpeechText).toHaveBeenCalledTimes(1))

    await act(async () => {
      settleFallback?.()
      await Promise.resolve()
      await Promise.resolve()
      await Promise.resolve()
    })

    expect($voicePlayback.get().status).toBe('idle')
    expect(playSpeechText).toHaveBeenCalledTimes(1)
  })
})

// Shared scaffolding for the conclusion-only debounce tests. Mirrors the
// pendingReply/markSpoken contract use-composer-voice.ts wires up; the test
// owns its own $messages atom so each case can stage its own transcript.
function setupConclusionOnlyHarness(opts: {
  sessionId?: string
  graceMs?: number
  initialConclusionOnly?: boolean
  initialReply?: ChatMessage
}) {
  const $messages = atom<ChatMessage[]>(opts.initialReply ? [opts.initialReply] : [])
  const sessionId = opts.sessionId ?? SESSION_ID

  const pendingReply = () => {
    const messages = $messages.get()
    const last = messages.findLast(m => m.role === 'assistant' && !m.hidden)
    const spoken = resolveSpokenReply(sessionId, messages)

    if (!last || last.id === spoken?.id) {
      return null
    }

    return { id: last.id, pending: Boolean(last.pending), text: chatMessageText(last) }
  }

  const markSpoken = () => {
    const messages = $messages.get()
    const last = messages.findLast(m => m.role === 'assistant' && !m.hidden)

    if (last) {
      markAssistantIdSpoken(sessionId, messages, last.id)
    }
  }

  if (opts.graceMs !== undefined) {
    $ttsConclusionGraceMs.set(opts.graceMs)
  }
  $ttsConclusionOnly.set(opts.initialConclusionOnly ?? true)

  const hook = renderHook(
    () =>
      useAutoSpeakReplies({
        conversationActive: false,
        failureLabel: 'read-aloud failed',
        markSpoken,
        pendingReply,
        sessionId
      }),
    {
      wrapper: ({ children }) => (
        <ComposerScopeProvider value={{ ...MAIN_COMPOSER_SCOPE, $messages }}>{children}</ComposerScopeProvider>
      )
    }
  )

  return { $messages, hook }
}

describe('useAutoSpeakReplies — voice.tts_conclusion_only debounce (#107056)', () => {
  beforeEach(() => {
    $autoSpeakReplies.set(true)
    $ttsConclusionOnly.set(false)
    $ttsConclusionGraceMs.set(1500)
    vi.mocked(playSpeechText).mockResolvedValue(true)
    // Must run before renderHook — useEffect captures setTimeout from whichever
    // timer API is active when the effect mounts.
    vi.useFakeTimers()
  })

  afterEach(() => {
    cleanup()
    clearSpokenRepliesForTests()
    $autoSpeakReplies.set(false)
    $ttsConclusionOnly.set(false)
    $ttsConclusionGraceMs.set(1500)
    setVoicePlaybackState({ ...IDLE_STATE })
    vi.useRealTimers()
    vi.clearAllMocks()
  })

  it('with conclusion-only off, every new completed reply speaks immediately (today\'s behavior)', async () => {
    $ttsConclusionOnly.set(false)

    const { $messages } = setupConclusionOnlyHarness({
      initialConclusionOnly: false,
      initialReply: assistantMessage('m-1', 'first chunk')
    })

    // Already mounted — initial useEffect ran markSpoken(), consuming m-1.
    // Push a new completed reply and expect immediate speak.
    await act(async () => {
      $messages.set([assistantMessage('m-1', 'first chunk'), assistantMessage('m-2', 'second chunk')])
      await Promise.resolve()
    })

    expect(playSpeechText).toHaveBeenCalledTimes(1)
    expect(vi.mocked(playSpeechText).mock.calls[0][0]).toBe('second chunk')
  })

  it('with conclusion-only on, a burst of interim replies collapses to a single speak after the grace window', async () => {
    const { $messages } = setupConclusionOnlyHarness({
      initialConclusionOnly: true,
      graceMs: 1500,
      initialReply: assistantMessage('m-1', 'first chunk')
    })

    // Stream three interim chunks before the grace window expires.
    await act(async () => {
      $messages.set([
        assistantMessage('m-1', 'first chunk'),
        assistantMessage('m-2', 'second chunk')
      ])
      await vi.advanceTimersByTimeAsync(500)
      $messages.set([
        assistantMessage('m-1', 'first chunk'),
        assistantMessage('m-2', 'second chunk'),
        assistantMessage('m-3', 'third chunk')
      ])
      await vi.advanceTimersByTimeAsync(500)
      $messages.set([
        assistantMessage('m-1', 'first chunk'),
        assistantMessage('m-2', 'second chunk'),
        assistantMessage('m-3', 'third chunk'),
        assistantMessage('m-final', 'final conclusion')
      ])
      // Mid-window — timer should still be pending.
      await vi.advanceTimersByTimeAsync(1000)
    })

    // Grace window has not expired yet — no speak.
    expect(playSpeechText).not.toHaveBeenCalled()

    // Advance past the full grace (1500ms total since last interim). The timer
    // callback resolves through ownsAmbientCue + playSpeechText synchronously
    // (both are mocked) — no waitFor needed.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(700)
    })
    expect(playSpeechText).toHaveBeenCalledTimes(1)
    expect(vi.mocked(playSpeechText).mock.calls[0][0]).toBe('final conclusion')
  })

  it('flipping conclusion-only off mid-window cancels the pending speak', async () => {
    const { $messages } = setupConclusionOnlyHarness({
      initialConclusionOnly: true,
      graceMs: 1500,
      initialReply: assistantMessage('m-1', 'baseline')
    })

    await act(async () => {
      $messages.set([
        assistantMessage('m-1', 'baseline'),
        assistantMessage('m-2', 'progress note')
      ])
      await vi.advanceTimersByTimeAsync(500)
    })

    expect(playSpeechText).not.toHaveBeenCalled()

    // Flip the flag off — pending timer should be cleared.
    await act(async () => {
      $ttsConclusionOnly.set(false)
    })

    // Run all pending timers — no speak should fire.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000)
    })

    expect(playSpeechText).not.toHaveBeenCalled()
  })

  it('when the grace timer fires while playback is still busy, the timer re-arms and speaks on the next idle', async () => {
    const { $messages } = setupConclusionOnlyHarness({
      initialConclusionOnly: true,
      graceMs: 200,
      initialReply: assistantMessage('m-1', 'lead-in')
    })

    // Stage a new reply and immediately mark playback busy BEFORE the timer
    // fires — simulating the previous clip still finishing.
    await act(async () => {
      $messages.set([
        assistantMessage('m-1', 'lead-in'),
        assistantMessage('m-final', 'final conclusion')
      ])
      setVoicePlaybackState({
        audioElement: null,
        messageId: 'm-1',
        sequence: 0,
        source: 'read-aloud',
        status: 'speaking'
      })
    })

    // Advance past the grace window while still busy — timer should re-arm.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500)
    })

    expect(playSpeechText).not.toHaveBeenCalled()

    // Now playback goes idle — re-arm should fire on the next poll of $voicePlayback.
    // The listen() subscription re-runs speakLatest, which (in conclusion-only mode)
    // calls scheduleConclusion() — and the new timer fires against the idle
    // $voicePlayback, reaching playSpeechText.
    await act(async () => {
      setVoicePlaybackState({ ...IDLE_STATE })
      await vi.advanceTimersByTimeAsync(2000)
    })

    expect(playSpeechText).toHaveBeenCalledTimes(1)
    expect(vi.mocked(playSpeechText).mock.calls[0][0]).toBe('final conclusion')
  })
})
