// CR-03 E: Firestore rules — a user can read only their own users/{uid} and cases; clients never write.
// Run: cd firestore-tests && npm install && npm test   (needs Java for the Firestore emulator)
import { readFileSync } from "node:fs";
import { after, before, beforeEach, test } from "node:test";
import { assertFails, assertSucceeds, initializeTestEnvironment } from "@firebase/rules-unit-testing";
import { doc, getDoc, setDoc, collection, getDocs } from "firebase/firestore";

let env;
before(async () => {
  env = await initializeTestEnvironment({
    projectId: "demo-recoverai",
    firestore: { rules: readFileSync(new URL("../firestore.rules", import.meta.url), "utf8") },
  });
});
after(async () => env.cleanup());
beforeEach(async () => {
  await env.clearFirestore();
  await env.withSecurityRulesDisabled(async (ctx) => {
    const db = ctx.firestore();
    await setDoc(doc(db, "users/alice"), { phoneE164: "+919000000001", profile: { fullName: "Alice" } });
    await setDoc(doc(db, "users/bob"), { phoneE164: "+919000000002", profile: { fullName: "Bob" } });
    await setDoc(doc(db, "cases/c_alice"), { ownerUid: "alice", country: "IN" });
    await setDoc(doc(db, "cases/c_alice/messages/m1"), { text: "hi" });
    await setDoc(doc(db, "cases/c_bob"), { ownerUid: "bob", country: "IN" });
    await setDoc(doc(db, "bank_cases/b1"), { caseId: "c_alice" });
  });
});

const as = (uid, claims = {}) => env.authenticatedContext(uid, claims).firestore();

test("a user reads their own profile", async () => {
  await assertSucceeds(getDoc(doc(as("alice"), "users/alice")));
});
test("a user cannot read another user's profile", async () => {
  await assertFails(getDoc(doc(as("alice"), "users/bob")));
});
test("signed-out clients cannot read profiles", async () => {
  await assertFails(getDoc(doc(env.unauthenticatedContext().firestore(), "users/alice")));
});
test("clients never write profiles (even their own)", async () => {
  await assertFails(setDoc(doc(as("alice"), "users/alice"), { profile: { fullName: "Eve" } }));
});
test("a user reads their own case and its messages", async () => {
  await assertSucceeds(getDoc(doc(as("alice"), "cases/c_alice")));
  await assertSucceeds(getDocs(collection(as("alice"), "cases/c_alice/messages")));
});
test("a user cannot read another user's case or its messages", async () => {
  await assertFails(getDoc(doc(as("alice"), "cases/c_bob")));
  await assertFails(getDocs(collection(as("bob"), "cases/c_alice/messages")));
});
test("clients never write cases", async () => {
  await assertFails(setDoc(doc(as("alice"), "cases/c_alice"), { ownerUid: "alice", status: "x" }));
});
test("victims cannot read bank cases; analysts with role=bank can", async () => {
  await assertFails(getDoc(doc(as("alice"), "bank_cases/b1")));
  await assertSucceeds(getDoc(doc(as("rahul", { role: "bank" }), "bank_cases/b1")));
});
test("a bank analyst cannot read victim profiles", async () => {
  await assertFails(getDoc(doc(as("rahul", { role: "bank" }), "users/alice")));
});
