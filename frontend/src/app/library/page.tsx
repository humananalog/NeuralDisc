"use client";

import { MediaGrid } from "@/components/MediaGrid";

export default function LibraryPage() {
  return <MediaGrid sort="taken_at_desc" />;
}
