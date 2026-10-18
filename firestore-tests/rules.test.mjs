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
    await setDoc(doc(db, "bank_access_requests/priya"), { uid: "priya", status: "PENDING", fullName: "Priya" });
    await setDoc(doc(db, "bank_access_requests/kiran"), { uid: "kiran", status: "APPROVED", fullName: "Kiran" });
    await setDoc(doc(db, "bank_access_requests/dev"), { uid: "dev", status: "REVOKED", fullName: "Dev" });
    await setDoc(doc(db, "admin_audit/a1"), { action: "approve", targetUid: "kiran" });
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

// CR-04: bank access requests and the admin audit log
test("an applicant reads only their own access request", async () => {
  await assertSucceeds(getDoc(doc(as("priya"), "bank_access_requests/priya")));
  await assertFails(getDoc(doc(as("priya"), "bank_access_requests/kiran")));
  await assertFails(getDoc(doc(as("alice"), "bank_access_requests/priya")));
  await assertFails(getDoc(doc(env.unauthenticatedContext().firestore(), "bank_access_requests/priya")));
});
test("admins read all access requests and the audit log; others cannot", async () => {
  await assertSucceeds(getDoc(doc(as("root", { role: "admin" }), "bank_access_requests/priya")));
  await assertSucceeds(getDocs(collection(as("root", { role: "admin" }), "bank_access_requests")));
  await assertSucceeds(getDoc(doc(as("root", { role: "admin" }), "admin_audit/a1")));
  await assertFails(getDoc(doc(as("rahul", { role: "bank" }), "admin_audit/a1")));
  await assertFails(getDocs(collection(as("rahul", { role: "bank" }), "bank_access_requests")));
});
test("nobody writes access requests or audit entries from the client (no self-approval)", async () => {
  await assertFails(setDoc(doc(as("priya"), "bank_access_requests/priya"), { status: "APPROVED" }));
  await assertFails(setDoc(doc(as("root", { role: "admin" }), "bank_access_requests/priya"), { status: "APPROVED" }));
  await assertFails(setDoc(doc(as("root", { role: "admin" }), "admin_audit/x"), { action: "approve" }));
});
test("an approved applicant with role=bank reads bank cases; a revoked one does not, even with the old claim", async () => {
  await assertSucceeds(getDoc(doc(as("kiran", { role: "bank" }), "bank_cases/b1")));
  await assertFails(getDoc(doc(as("dev", { role: "bank" }), "bank_cases/b1")));
  await assertFails(getDoc(doc(as("priya", { role: "bank" }), "bank_cases/b1")));
  await assertFails(getDoc(doc(as("priya"), "bank_cases/b1")));
});
