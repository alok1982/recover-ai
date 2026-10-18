/** CR-04: staff accounts (bank applicants, approved bank staff, admins) — work email + password on the separate
 *  "bank" Firebase app instance, so a victim session in the same browser is untouched. Roles come only from
 *  server-set custom claims; the client merely refreshes its ID token to pick them up. */
import {
  createUserWithEmailAndPassword, deleteUser, getAuth, signInWithEmailAndPassword, signOut,
} from "firebase/auth";
import { API_BASE, MOCK } from "./config";
import { AuthError, setBankSession } from "./auth";
import { analystApp } from "./firebase";

const MOCK_STAFF = "recoverai.mockStaff";
const MOCK_ACCOUNTS = "recoverai.mockStaffAccounts";
export const ADMIN_EMAIL = "admin@recoverai-demo.example";
export const ANALYST_EMAIL = "analyst@recoverai-demo.example";
// mock mode only: the seeded staff accounts sign in with the published demo password
const MOCK_SEEDED = [ADMIN_EMAIL, ANALYST_EMAIL, "pending.applicant@demo-bank.example"];

export type RequestStatus = "PENDING" | "APPROVED" | "REJECTED" | "REVOKED";
export interface AccessRequest {
  uid: string; email: string | null; fullName: string; country: "IN" | "MY"; bankName: string; bankOther?: string | null;
  employeeId: string; designation: string; note?: string | null; status: RequestStatus; createdAt?: string;
  updatedAt?: string; decidedBy?: string | null; decidedAt?: string | null; reason?: string | null; bankId?: string | null;
}
export interface StaffMe {
  uid: string; accountType: "staff" | "victim"; email: string | null; role: "bank" | "admin" | "victim" | null;
  requestStatus: RequestStatus | null; request: AccessRequest | null; banks: Record<string, string[]>;
}

async function sha(s: string): Promise<string> {
  const b = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
  return Array.from(new Uint8Array(b)).map((x) => x.toString(16).padStart(2, "0")).join("");
}
const mockAccounts = (): Record<string, string> => JSON.parse(localStorage.getItem(MOCK_ACCOUNTS) || "{}");

function mapFirebase(e: any): AuthError {
  const c = String(e?.code || "");
  if (/invalid-credential|wrong-password|user-not-found|invalid-email|too-many-requests|user-disabled/.test(c)) return new AuthError("bad_credentials");
  if (/email-already-in-use/.test(c)) return new AuthError("exists");
  if (/weak-password/.test(c)) return new AuthError("weak");
  if (/network/.test(c)) return new AuthError("network");
  return new AuthError("other", e?.message);
}

export const staffAuth = () => getAuth(analystApp());

export async function staffSignUp(email: string, password: string): Promise<void> {
  email = email.trim().toLowerCase();
  if (MOCK) {
    const acc = mockAccounts();
    if (acc[email] || MOCK_SEEDED.includes(email)) throw new AuthError("exists");
    acc[email] = await sha(password);
    localStorage.setItem(MOCK_ACCOUNTS, JSON.stringify(acc));
    localStorage.setItem(MOCK_STAFF, email);
    return;
  }
  try {
    await createUserWithEmailAndPassword(staffAuth(), email, password);
  } catch (e) {
    throw mapFirebase(e);
  }
}

export async function staffSignIn(email: string, password: string): Promise<void> {
  email = email.trim().toLowerCase();
  if (MOCK) {
    const ok = (MOCK_SEEDED.includes(email) && password === "Demo@2026") || mockAccounts()[email] === (await sha(password));
    if (!ok) throw new AuthError("bad_credentials");
    localStorage.setItem(MOCK_STAFF, email);
    return;
  }
  try {
    await signInWithEmailAndPassword(staffAuth(), email, password);
  } catch (e) {
    throw mapFirebase(e);
  }
}

export async function staffSignOut(): Promise<void> {
  sessionStorage.removeItem("recoverai.bankUser");
  if (MOCK) { localStorage.removeItem(MOCK_STAFF); return; }
  await signOut(staffAuth());
}

export async function staffSignedIn(): Promise<string | null> {
  if (MOCK) return localStorage.getItem(MOCK_STAFF);
  await staffAuth().authStateReady();
  return staffAuth().currentUser?.email ?? null;
}

/** ID token of the staff account; `force` re-fetches it so newly approved/revoked claims apply (CR-04). */
export async function staffToken(force = false): Promise<string> {
  if (MOCK) {
    const e = localStorage.getItem(MOCK_STAFF);
    if (!e) throw new AuthError("other", "Please sign in.");
    return e === ADMIN_EMAIL ? "mock:admin:Admin" : e === ANALYST_EMAIL ? "mock:bank:Analyst" : `mock:staff:${e}`;
  }
  const auth = staffAuth();
  await auth.authStateReady();
  if (!auth.currentUser) throw new AuthError("other", "Please sign in.");
  return auth.currentUser.getIdToken(force);
}

export class StaffApiError extends Error {
  constructor(public status: number, public detail: any) {
    super(typeof detail === "string" ? detail : detail?.message || detail?.code || `HTTP ${status}`);
  }
}

export async function staffApi<T>(method: string, path: string, body?: unknown, force = false): Promise<T> {
  const token = await staffToken(force);
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: { Authorization: `Bearer ${token}`, ...(body !== undefined ? { "Content-Type": "application/json" } : {}) },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let d: any = res.statusText;
    try { d = (await res.json()).detail ?? d; } catch { /* ignore */ }
    throw new StaffApiError(res.status, d);
  }
  return res.json() as Promise<T>;
}

export const staffMe = (force = false) => staffApi<StaffMe>("GET", "/api/me", undefined, force);

export interface AccessForm {
  fullName: string; country: "IN" | "MY"; bankName: string; bankOther?: string; employeeId: string; designation: string; note?: string;
}
export const requestBankAccess = (f: AccessForm) => staffApi<AccessRequest>("POST", "/api/bank-access/request", f);

function safe(n: string | null, prefix: string): string | null {
  return n && n.startsWith(prefix) && !n.startsWith("//") ? n : null;
}

/** Single login, role-based redirect: bank → bank desk, admin → admin console, applicant → pending page. */
export function staffDestination(me: StaffMe, next: string | null): string {
  if (me.role === "admin") return safe(next, "/admin") || "/admin";
  if (me.role === "bank") return safe(next, "/bank") || "/bank";
  return "/pending";
}

/** After a staff sign-in: refresh the token (claims), ask the server for the role, open the right place. */
export async function routeStaff(next: string | null): Promise<string> {
  const me = await staffMe(true);
  if (me.role === "bank") setBankSession(me.request?.fullName || me.email || "Analyst", me.email || undefined);
  return staffDestination(me, next);
}

/** Staff account self-deletion (test cleanup / "delete my application"): request removed server-side, then login. */
export async function staffDeleteAccount(): Promise<void> {
  await staffApi("DELETE", "/api/me");
  if (MOCK) {
    const e = localStorage.getItem(MOCK_STAFF);
    const acc = mockAccounts();
    if (e) delete acc[e];
    localStorage.setItem(MOCK_ACCOUNTS, JSON.stringify(acc));
  } else if (staffAuth().currentUser) {
    await deleteUser(staffAuth().currentUser!);
  }
  await staffSignOut();
}
