import "server-only";
import Anthropic from "@anthropic-ai/sdk";

/** The Claude model every agent uses. Bump the version here, once. */
export const MODEL = "claude-opus-4-8";

/** All agents need the Anthropic API key to run. */
export const isAnthropicConfigured = (): boolean => Boolean(process.env.ANTHROPIC_API_KEY);

let client: Anthropic | null = null;
/** Shared Anthropic client (reads ANTHROPIC_API_KEY from the environment). */
export const anthropic = (): Anthropic => (client ??= new Anthropic());
