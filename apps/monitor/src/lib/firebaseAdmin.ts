import { getApps, initializeApp } from "firebase-admin/app";
import { getAuth } from "firebase-admin/auth";
import { getFirestore } from "firebase-admin/firestore";

function app() {
  if (!getApps().length) initializeApp({ projectId: process.env.FIREBASE_PROJECT_ID || "hushdev" });
  return getApps()[0]!;
}

export function adminAuth() {
  return getAuth(app());
}

export function adminDb() {
  return getFirestore(app());
}
