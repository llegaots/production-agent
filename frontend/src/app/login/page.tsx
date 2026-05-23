"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { createBrowserClient } from "@supabase/ssr";
import { getSupabaseConfig, supabaseConfigError } from "@/lib/supabase/config";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

function createSupabaseBrowserClient() {
  if (typeof window === "undefined") {
    return null;
  }
  const { url, anonKey } = getSupabaseConfig();
  if (!url || !anonKey) {
    return null;
  }
  return createBrowserClient(url, anonKey);
}

export default function LoginPage() {
  const router = useRouter();
  const supabase = useMemo(() => createSupabaseBrowserClient(), []);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const configError = supabaseConfigError();

  async function handleSignIn(e: React.FormEvent) {
    e.preventDefault();
    if (configError) {
      setError(configError);
      return;
    }
    if (!supabase) {
      setError("Supabase is not configured. Check repo-root .env (SUPABASE_URL, SUPABASE_SERVICE_KEY).");
      return;
    }
    setLoading(true);
    setError(null);
    const { error: err } = await supabase.auth.signInWithPassword({ email, password });
    setLoading(false);
    if (err) {
      setError(err.message);
      return;
    }
    router.push("/chat");
    router.refresh();
  }

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Dispatcher sign in</CardTitle>
          <CardDescription>
            Supabase Auth — create a user in your project dashboard (Authentication → Users).
            <br />
            <a href="/optimizer-lab" className="text-primary mt-2 inline-block underline">
              Open Optimizer Lab (no login)
            </a>
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={(e) => void handleSignIn(e)} className="space-y-4">
            <Input
              type="email"
              placeholder="email@company.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
            <Input
              type="password"
              placeholder="Password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
            {configError ? (
              <p className="text-destructive text-sm">{configError}</p>
            ) : null}
            {error ? <p className="text-destructive text-sm">{error}</p> : null}
            <Button type="submit" className="w-full" disabled={loading || Boolean(configError)}>
              {loading ? "Signing in…" : "Sign in"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
