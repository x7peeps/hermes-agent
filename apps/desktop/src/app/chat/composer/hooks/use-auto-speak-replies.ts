import { useStore } from '@nanostores/react'
import { useEffect, useRef } from 'react'

import { playSpeechText } from '@/lib/voice-playback'
import { ownsAmbientCue } from '@/store/ambient'
import { notifyError } from '@/store/notifications'
import { $voicePlayback } from '@/store/voice-playback'
import {
  $autoSpeakReplies,
  $ttsConclusionGraceMs,
  $ttsConclusionOnly
} from '@/store/voice-prefs'

import { useComposerScope } from '../scope'

interface AutoSpeakReply {
  id: string
  pending: boolean
  text: string
}

interface UseAutoSpeakReplies {
  conversationActive: boolean
  failureLabel: string
  /** Mark the current last reply spoken — shared dedupe with the conversation consumer. */
  markSpoken: () => void
  /** Latest completed assistant reply, or null; `pending` true while still streaming. */
  pendingReply: () => AutoSpeakReply | null
  /** Re-arm on session switch so opening a chat never reads its existing last reply. */
  sessionId: string | null | undefined
}

/** Re-arm delay when the grace timer fires while a previous TTS clip is still playing.
 *  Short enough that the user perceives a continuous voice, long enough to skip a busy spin. */
const PLAYBACK_BUSY_REARM_MS = 200

/**
 * Pure-TTS auto-speak: when `voice.auto_tts` is on, read each completed assistant
 * turn aloud — no dictation, no conversation loop. Stays off while a full voice
 * conversation runs (it speaks replies itself) and never overlaps clips: a reply
 * landing mid-playback is held and spoken on the playback-idle edge. Always reads
 * the latest reply, so a backlog collapses to the newest.
 *
 * When `voice.tts_conclusion_only` is on, every new reply resets a quiet-window
 * timer instead of speaking immediately. Once the window passes without a fresh
 * chunk, the latest completed reply is voiced. If playback is still busy when
 * the timer fires, the timer re-arms (no swallowed final reply).
 */
export function useAutoSpeakReplies({
  conversationActive,
  failureLabel,
  markSpoken,
  pendingReply,
  sessionId
}: UseAutoSpeakReplies) {
  const enabled = useStore($autoSpeakReplies)
  const conclusionOnly = useStore($ttsConclusionOnly)
  const conclusionGraceMs = useStore($ttsConclusionGraceMs)
  // Wake on THIS composer's transcript: a tile subscribed to the primary's
  // would never fire on its own replies (and would fire on someone else's).
  const { $messages } = useComposerScope()
  const latest = useRef({
    conclusionGraceMs,
    conclusionOnly,
    conversationActive,
    failureLabel,
    markSpoken,
    pendingReply
  })
  latest.current = {
    conclusionGraceMs,
    conclusionOnly,
    conversationActive,
    failureLabel,
    markSpoken,
    pendingReply
  }
  // Pending conclusion-only timer (ref only — never read inside render). Cleared
  // on unmount, session switch, auto-speak toggle off, and conclusion-only flip.
  const conclusionTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  function cancelConclusionTimer() {
    if (conclusionTimerRef.current) {
      clearTimeout(conclusionTimerRef.current)
      conclusionTimerRef.current = null
    }
  }

  function scheduleConclusion(delayMs?: number) {
    cancelConclusionTimer()
    const { conclusionGraceMs } = latest.current
    const effectiveDelay = typeof delayMs === 'number' ? Math.max(0, delayMs) : Math.max(0, conclusionGraceMs)
    conclusionTimerRef.current = setTimeout(() => {
      conclusionTimerRef.current = null
      if ($voicePlayback.get().status !== 'idle') {
        // Previous TTS clip still finishing — re-arm with a short delay.
        scheduleConclusion(PLAYBACK_BUSY_REARM_MS)
        return
      }
      const { conversationActive, markSpoken, pendingReply } = latest.current
      if (conversationActive) {
        return
      }
      const reply = pendingReply()
      if (!reply || reply.pending) {
        return
      }
      markSpoken()
      void ownsAmbientCue(`speak:${reply.id}`).then(owns => {
        if (owns) {
          void playSpeechText(reply.text, { messageId: reply.id, source: 'read-aloud' }).catch(error =>
            notifyError(error, latest.current.failureLabel)
          )
        }
      })
    }, effectiveDelay)
  }

  useEffect(() => {
    if (!enabled) {
      cancelConclusionTimer()
      return undefined
    }

    // Don't read whatever reply already sits at the bottom when the toggle flips
    // on (or a chat opens) — consume it so only later replies are spoken.
    latest.current.markSpoken()

    const speakLatest = () => {
      const { conclusionOnly, conversationActive, pendingReply } = latest.current

      if (conversationActive || $voicePlayback.get().status !== 'idle') {
        // Even when we can't speak now, keep the conclusion timer armed so the
        // final reply still gets voiced once playback goes idle.
        if (conclusionOnly) {
          scheduleConclusion()
        }
        return
      }

      const reply = pendingReply()

      if (!reply || reply.pending) {
        return
      }

      if (conclusionOnly) {
        // Defer until the stream settles; speakLatest will reset the timer if
        // a newer reply arrives before it fires.
        scheduleConclusion()
        return
      }

      markSpoken()
      void ownsAmbientCue(`speak:${reply.id}`).then(owns => {
        if (owns) {
          void playSpeechText(reply.text, { messageId: reply.id, source: 'read-aloud' }).catch(error =>
            notifyError(error, latest.current.failureLabel)
          )
        }
      })
    }

    // Re-check on a reply completing ($messages) and on the prior clip ending
    // ($voicePlayback → idle), which frees us to read the next held reply.
    const stops = [$messages.subscribe(speakLatest), $voicePlayback.listen(speakLatest)]

    return () => {
      stops.forEach(f => f())
      cancelConclusionTimer()
    }
  }, [$messages, enabled, sessionId, conclusionOnly])

  // If conclusion-only flips off mid-window, drop any pending timer — the next
  // $messages update will speak immediately under the default path.
  useEffect(() => {
    if (!conclusionOnly) {
      cancelConclusionTimer()
    }
  }, [conclusionOnly])
}
