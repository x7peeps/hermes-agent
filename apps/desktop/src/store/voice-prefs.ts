import { atom } from 'nanostores'

import { persistBoolean, readKey, storedBoolean } from '@/lib/storage'

// Desktop read-aloud is local; voice.auto_tts belongs to the messaging gateway.
const AUTO_SPEAK_KEY = 'hermes.desktop.autoSpeakReplies'
export const $autoSpeakReplies = atom<boolean>(storedBoolean(AUTO_SPEAK_KEY, false))
// Desktop-only auto-speak debounce: when on, interim progress is held back and
// only the final reply of each turn is voiced. Source of truth is config
// (`voice.tts_conclusion_only`); this atom is a local mirror like $autoSpeakReplies.
export const $ttsConclusionOnly = atom<boolean>(false)
export const $ttsConclusionGraceMs = atom<number>(1500)
// Best-effort persistence must not give config refresh authority again.
let autoSpeakChosen = readKey(AUTO_SPEAK_KEY) !== null

/** Migrate the legacy value once without editing the backend configuration. */
export function applyAutoSpeakFromConfig(config: { voice?: { auto_tts?: unknown } | null } | null | undefined) {
  if (config != null && !autoSpeakChosen) {
    void setAutoSpeakReplies(Boolean(config.voice?.auto_tts))
  }
}

// First configured `voice.stop_phrases` entry — drives the "Say "stop" to end
// the voice chat" notice shown when a voice conversation starts. `null` means
// the user disabled stop phrases (`stop_phrases: []`), so no notice is shown.
// Defaults to "stop" (the backend default) before config loads.
export const $voiceStopPhrase = atom<string | null>('stop')

/** Seed the stop-phrase atom from a loaded config payload (mount / refresh). */
export function applyVoiceStopPhraseFromConfig(
  config: { voice?: { stop_phrases?: unknown } | null } | null | undefined
) {
  const raw = config?.voice?.stop_phrases

  if (raw === undefined) {
    // Key absent — backend default applies.
    $voiceStopPhrase.set('stop')

    return
  }

  const list = Array.isArray(raw) ? raw : typeof raw === 'string' ? [raw] : []
  const first = list.map(entry => String(entry).trim()).find(entry => entry.length > 0)

  $voiceStopPhrase.set(first ?? null)
}

// `voice.thinking_sound` — ambient bubble blips while the agent works during a
// voice conversation (default on, matching the backend default).
export const $thinkingSoundEnabled = atom<boolean>(true)

/** Seed the thinking-sound gate from a loaded config payload. */
export function applyThinkingSoundFromConfig(
  config: { voice?: { thinking_sound?: unknown } | null } | null | undefined
) {
  $thinkingSoundEnabled.set(config?.voice?.thinking_sound !== false)
}

/**
 * Seed the conclusion-only debounce from a loaded config payload. Config is the
 * source of truth — flipping the toggle in Settings calls `setConclusionOnly`
 * which writes back so the next config refresh sees the choice.
 */
export function applyConclusionOnlyFromConfig(
  config: { voice?: { tts_conclusion_only?: unknown; tts_conclusion_grace_ms?: unknown } | null } | null | undefined
) {
  $ttsConclusionOnly.set(config?.voice?.tts_conclusion_only === true)
  const rawGrace = config?.voice?.tts_conclusion_grace_ms
  if (typeof rawGrace === 'number' && Number.isFinite(rawGrace) && rawGrace >= 0) {
    $ttsConclusionGraceMs.set(rawGrace)
  }
}

/** Local setter for the conclusion-only gate. Kept in sync with config writes upstream. */
export function setTtsConclusionOnly(enabled: boolean) {
  $ttsConclusionOnly.set(enabled)
}

/** Local setter for the conclusion-only grace window (ms). */
export function setTtsConclusionGraceMs(ms: number) {
  if (!Number.isFinite(ms) || ms < 0) return
  $ttsConclusionGraceMs.set(ms)
}

/** Persist even an unchanged value, so migrating false is also one-time. */
export async function setAutoSpeakReplies(enabled: boolean): Promise<void> {
  autoSpeakChosen = true
  persistBoolean(AUTO_SPEAK_KEY, enabled)
  $autoSpeakReplies.set(enabled)
}
