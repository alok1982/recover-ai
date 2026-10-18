import {
  createUserWithEmailAndPassword, deleteUser, EmailAuthProvider, getAuth, onAuthStateChanged,
  reauthenticateWithCredential, signInWithEmailAndPassword, signOut,
} from "firebase/auth";
import { useEffect, useState } from "react";
import { MOCK } from "./config";
import { analystApp, signedInVictim, victimAuth } from "./firebase";
import { phoneEmail } from "./phone";

const BANK_KEY = "recoverai.bankUser";
const MOCK_ACCOUNTS = "recoverai.mockAccounts";
const MOCK_SESSION = "recoverai.mockSession";

export class AuthError extends Error {
  constructor(public code: "bad_credentials" | "exists" | "weak" | "network" | "other", message: string = code) {
    super(message);
  }
}

// ------------------------------------------------------------------ victim (CR-03: phone + password)
const listeners = new Set<(p: string | null) => void>();

async function sha(s: string): Promise<string> {
  const b = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
  return Array.from(new Uint8Array(b)).map((x) => x.toString(16).padStart(2, "0")).join("");
}

function mockAccounts(): Record<string, string> {
  return JSON.parse(localStorage.getItem(MOCK_ACCOUNTS) || "{}");
}

function mapFirebase(e: any): AuthError {
  const c = String(e?.code || "");
  if (/invalid-credential|wrong-password|user-not-found|invalid-email|too-many-requests|user-disabled/.test(c)) return new AuthError("bad_credentials");
  if (/email-already-in-use/.test(c)) return new AuthError("exists");
  if (/weak-password/.test(c)) return new AuthError("weak");
  if (/network/.test(c)) return new AuthError("network");
  return new AuthError("other", e?.message);
}

export async function victimSignUp(e164: string, password: string): Promise<void> {
  if (MOCK) {
    const acc = mockAccounts();
    if (acc[e164]) throw new AuthError("exists");
    acc[e164] = await sha(password);
    localStorage.setItem(MOCK_ACCOUNTS, JSON.stringify(acc));
    localStorage.setItem(MOCK_SESSION, e164);
    listeners.forEach((f) => f(e164));
    return;
  }
  try {
    await createUserWithEmailAndPassword(victimAuth(), phoneEmail(e164), password);
  } catch (e) {
    throw mapFirebase(e);
  }
}

export async function victimSignIn(e164: string, password: string): Promise<void> {
  if (MOCK) {
    const acc = mockAccounts();
    // seed users (scripts/seed_users.py) exist server-side only; in mock mode they log in with the demo password
    const seeded = /^\+91900000000[1-3]$|^\+601000000(01|02)$/.test(e164) && password === "Demo@2026";
    if (!seeded && acc[e164] !== (await sha(password))) throw new AuthError("bad_credentials");
    localStorage.setItem(MOCK_SESSION, e164);
    listeners.forEach((f) => f(e164));
    return;
  }
  try {
    await signInWithEmailAndPassword(victimAuth(), phoneEmail(e164), password);
  } catch (e) {
    throw mapFirebase(e);
  }
}

export async function victimSignOut(): Promise<void> {
  localStorage.removeItem("recoverai.lastCase");
  if (MOCK) {
    localStorage.removeItem(MOCK_SESSION);
    listeners.forEach((f) => f(null));
    return;
  }
  await signOut(victimAuth());
}

/** After DELETE /api/me removed the profile and cases: delete the login itself, then drop the local session.
 *  The victim deletes their own Firebase user (no admin rights needed on the server); Firebase asks for a
 *  recent sign-in, so on auth/requires-recent-login we re-check the password once. Mock: drop the local account. */
export async function victimForget(askPassword?: () => string | null): Promise<void> {
  if (MOCK) {
    const p = localStorage.getItem(MOCK_SESSION);
    const acc = mockAccounts();
    if (p) delete acc[p];
    localStorage.setItem(MOCK_ACCOUNTS, JSON.stringify(acc));
  } else {
    const u = victimAuth().currentUser;
    if (u) {
      try {
        await deleteUser(u);
      } catch (e) {
        const pw = (e as { code?: string })?.code === "auth/requires-recent-login" ? askPassword?.() : null;
        if (!pw || !u.email) throw mapFirebase(e);
        try {
          await reauthenticateWithCredential(u, EmailAuthProvider.credential(u.email, pw));
          await deleteUser(u);
        } catch (e2) {
          throw mapFirebase(e2);
        }
      }
    }
  }
  await victimSignOut();
}

/** Signed-in victim id (mock: E.164; Firebase: uid), or null. */
export async function victimId(): Promise<string | null> {
  if (MOCK) return localStorage.getItem(MOCK_SESSION);
  const u = await signedInVictim();
  return u && !u.isAnonymous ? u.uid : null;
}

/** ID token for /api/* victim routes. Throws when signed out (the route guards send the user to /login). */
export async function victimToken(): Promise<string> {
  if (MOCK) {
    const p = localStorage.getItem(MOCK_SESSION);
    if (!p) throw new AuthError("other", "Please sign in.");
    return `mock:phone:${p}`;
  }
  const u = await signedInVictim();
  if (!u || u.isAnonymous) throw new AuthError("other", "Please sign in.");
  return u.getIdToken();
}

/** React hook: undefined while loading, null when signed out, else the victim id. */
export function useVictim(): string | null | undefined {
  const [v, setV] = useState<string | null | undefined>(MOCK ? localStorage.getItem(MOCK_SESSION) : undefined);
  useEffect(() => {
    if (MOCK) {
      const f = (p: string | null) => setV(p);
      listeners.add(f);
      return () => { listeners.delete(f); };
    }
    return onAuthStateChanged(victimAuth(), (u) => setV(u && !u.isAnonymous ? u.uid : null));
  }, []);
  return v;
}

// ------------------------------------------------------------------ bank analyst (unchanged)
export interface BankUser {
  name: string;
  email?: string;
}

export function currentBankUser(): BankUser | null {
  const raw = sessionStorage.getItem(BANK_KEY);
  if (!raw) return null;
  if (!MOCK && !getAuth(analystApp()).currentUser) return JSON.parse(raw); // restored lazily by Firebase
  return JSON.parse(raw);
}

export async function bankLogin(name: string, email: string, password: string): Promise<BankUser> {
  if (!MOCK) {
    const cred = await signInWithEmailAndPassword(getAuth(analystApp()), email, password);
    const res = await cred.user.getIdTokenResult();
    if (res.claims.role !== "bank") {
      await signOut(getAuth(analystApp()));
      throw new Error("This account does not have the bank analyst role.");
    }
  }
  const u = { name: name || "Analyst", email };
  sessionStorage.setItem(BANK_KEY, JSON.stringify(u));
  return u;
}

/** CR-04: an approved staff member who signed in through the single login opens the bank desk directly. */
export function setBankSession(name: string, email?: string): void {
  sessionStorage.setItem(BANK_KEY, JSON.stringify({ name, email }));
}

export async function bankLogout(): Promise<void> {
  sessionStorage.removeItem(BANK_KEY);
  if (!MOCK) await signOut(getAuth(analystApp()));
}

export async function bankToken(): Promise<string> {
  if (MOCK) {
    const u = currentBankUser();
    return `mock:bank:${(u?.name || "Analyst").replace(/:/g, " ")}`;
  }
  const auth = getAuth(analystApp());
  await auth.authStateReady();
  if (!auth.currentUser) throw new Error("Please sign in again.");
  return auth.currentUser.getIdToken();
}
