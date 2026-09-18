"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import { whoAmI, type Account } from "@/lib/api";
import { claimAliases, getProfile, type Profile } from "@/lib/profile";

/**
 * Who is using the app, whether or not they have an account.
 *
 * Both identities exist on purpose. A browser id lets someone try the thing
 * without signing up, which is most of the people who will ever open it. An
 * account makes that library survive a cleared cache and follow them to
 * another machine. The server prefers the session when both are present, and
 * this mirrors that: `userId` is the account key when signed in and the
 * browser id otherwise, so callers do not each have to decide.
 */

type SessionValue = {
  account: Account | null;
  /** The key the API should act as: the account, or this browser. */
  userId: string;
  /** The browser profile, still used for its remembered display name. */
  profile: Profile | null;
  loading: boolean;
  /** Browser ids whose courses should move across on sign-in. */
  claim: string[];
  setAccount: (account: Account | null) => void;
  refresh: () => Promise<void>;
};

const SessionContext = createContext<SessionValue | null>(null);

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [account, setAccount] = useState<Account | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      setAccount(await whoAmI());
    } catch {
      setAccount(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // getProfile reads localStorage, so it runs after hydration rather than in
    // a lazy initializer: the server renders an "anonymous" stub, and reading
    // early makes the first client render disagree with it.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setProfile(getProfile());
    void refresh();
  }, [refresh]);

  const value = useMemo<SessionValue>(() => {
    const browserId = profile?.id ?? "anonymous";
    return {
      account,
      userId: account ? account.key : browserId,
      profile,
      loading,
      claim: profile ? [browserId, ...claimAliases(profile)] : [],
      setAccount,
      refresh,
    };
  }, [account, profile, loading, refresh]);

  return (
    <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
  );
}

export function useSession(): SessionValue {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession must be used inside SessionProvider");
  return value;
}
