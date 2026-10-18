import { initializeApp, type FirebaseApp } from "firebase/app";
import { getAuth, type Auth, type User } from "firebase/auth";
import { getFirestore, type Firestore } from "firebase/firestore";
import { FIREBASE_CONFIG, MOCK } from "./config";

let app: FirebaseApp | null = null;
let bankApp: FirebaseApp | null = null;

export function victimApp(): FirebaseApp {
  if (!app) app = initializeApp(FIREBASE_CONFIG);
  return app;
}

/** The analyst signs in on a separate Firebase app instance so a victim session in the same browser is untouched. */
export function analystApp(): FirebaseApp {
  if (!bankApp) bankApp = initializeApp(FIREBASE_CONFIG, "bank");
  return bankApp;
}

export function victimAuth(): Auth {
  return getAuth(victimApp());
}

export function victimDb(): Firestore {
  return getFirestore(victimApp());
}

export function bankDb(): Firestore {
  return getFirestore(analystApp());
}

/** CR-03: the signed-in victim (phone + password account). Resolves once Firebase has restored the session. */
export async function signedInVictim(): Promise<User | null> {
  if (MOCK) throw new Error("not in mock mode");
  const auth = victimAuth();
  await auth.authStateReady();
  return auth.currentUser;
}
