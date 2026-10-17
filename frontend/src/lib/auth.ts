import { signInWithEmailAndPassword, getAuth, signOut } from "firebase/auth";
import { MOCK } from "./config";
import { analystApp, ensureAnonymous } from "./firebase";

const MOCK_UID_KEY = "recoverai.mockUid";
const BANK_KEY = "recoverai.bankUser";

function mockUid(): string {
  let uid = localStorage.getItem(MOCK_UID_KEY);
  if (!uid) {
    uid = "anon-" + Math.random().toString(36).slice(2, 12);
    localStorage.setItem(MOCK_UID_KEY, uid);
  }
  return uid;
}

/** Victim: Firebase Anonymous Auth ID token (or a mock token offline). */
export async function victimToken(): Promise<string> {
  if (MOCK) return `mock:${mockUid()}`;
  const user = await ensureAnonymous();
  return user.getIdToken();
}

export async function victimUid(): Promise<string> {
  if (MOCK) return mockUid();
  return (await ensureAnonymous()).uid;
}

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
