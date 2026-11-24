"use client";

import { useEffect, useState } from "react";

const KEY = "evidencex.reviewer";

/**
 * The reviewer name recorded with each decision. There is no login in the MVP, so
 * this is a self-declared label kept in this browser only.
 */
export function useReviewer(): [string, (name: string) => void] {
  const [name, setName] = useState("");
  useEffect(() => {
    try {
      setName(window.localStorage.getItem(KEY) ?? "");
    } catch {
      setName("");
    }
  }, []);
  const update = (value: string) => {
    const trimmed = value.slice(0, 128);
    setName(trimmed);
    try {
      window.localStorage.setItem(KEY, trimmed);
    } catch {
      // storage unavailable: keep the name for this page only
    }
  };
  return [name, update];
}
