-- ============================================================================
-- RouteIQ - Voice enrollment. Each marketer can enroll a voiceprint so live
-- transcription can tell the marketer (rep) apart from the prospect by voice,
-- instead of guessing from who spoke first. `voice_profile` holds the
-- speaker-recognition enrollment blob (base64); a session loads its marketer's
-- profile to score, in real time, whether the current voice is the rep.
-- Safe to re-run. Run after 0001 (D2D_Marketers must exist).
-- ============================================================================

alter table "D2D_Marketers"
  -- base64 speaker-recognition enrollment blob; null until the marketer calibrates
  add column if not exists voice_profile     text,
  -- when the voiceprint was last (re)enrolled
  add column if not exists voice_enrolled_at timestamptz;
