import { initializeApp, type FirebaseApp } from "firebase/app";
import { getAuth, signInAnonymously, onAuthStateChanged, type Auth, type User } from "firebase/auth";
import { getFirestore, type Firestore } from "firebase/firestore";
import { FIREBASE_CONFIG, MOCK } from "./config";

let app: FirebaseApp | null = null;
let bankApp: FirebaseApp | null = null;

export function victimApp(): FirebaseApp {
  if (!app) app = initializeApp(FIREBASE_CONFIG);
  return app;
}

/** The analyst signs in on a separate Firebase app instance so the victim's anonymous session is untouched. */
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

let ready: Promise<User> | null = null;

export function ensureAnonymous(): Promise<User> {
  if (MOCK) throw new Error("not in mock mode");
  if (!ready) {
    const auth = victimAuth();
    ready = new Promise<User>((resolve, reject) => {
      const unsub = onAuthStateChanged(auth, (u) => {
        if (u) {
          unsub();
          resolve(u);
        }
      });
      if (!auth.currentUser) signInAnonymously(auth).catch(reject);
    });
  }
  return ready;
}
