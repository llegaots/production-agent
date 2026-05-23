-- Phase 5: richer critic_feedback fields for deterministic metrics + LLM output

ALTER TABLE public.critic_feedback
  ADD COLUMN IF NOT EXISTS metrics jsonb,
  ADD COLUMN IF NOT EXISTS feedback_prompt text,
  ADD COLUMN IF NOT EXISTS issues text[] NOT NULL DEFAULT '{}';

COMMENT ON COLUMN public.critic_feedback.metrics IS
  'Deterministic checker output (drive, spread, fill scores, etc.).';
COMMENT ON COLUMN public.critic_feedback.feedback_prompt IS
  'Actionable prompt for the orchestrator to revise the schedule.';
COMMENT ON COLUMN public.critic_feedback.issues IS
  'Structured issue strings from the LLM critic.';
