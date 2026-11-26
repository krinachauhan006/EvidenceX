// CSS-only artwork for the landing page. It replaces photographs whose usage rights
// were not verified (see LANDING_IMAGES.md). Pure gradients drawn by the browser: no
// image files, no requests, nothing third-party. Same layering as SectionPhoto: art,
// then an overlay, then the top/bottom fade and film grain. Text sits above at full
// opacity.

import clsx from "clsx";

export type BackdropArt = "desk" | "scatter" | "threads" | "lamp";
export type FramedArtKind = "map" | "ridges";

/** Full-bleed decorative backdrop behind a section. */
export function SectionBackdrop({
  art,
  overlay,
  className,
}: {
  art: BackdropArt;
  overlay: string;
  className?: string;
}) {
  return (
    <div aria-hidden className={clsx("pointer-events-none absolute inset-0 -z-10 overflow-hidden", className)} data-backdrop={art}>
      <div className={`evx-art evx-art-${art} absolute inset-0`} data-backdrop-art />
      <div className={clsx("absolute inset-0", overlay)} />
      <div className="absolute inset-0 bg-[linear-gradient(to_bottom,#0a0f1a_0%,transparent_16%,transparent_84%,#0a0f1a_100%)]" />
      <div className="evx-grain absolute inset-0" />
    </div>
  );
}

/** A framed decorative illustration beside text (same frame as FramedPhoto). */
export function FramedArt({
  kind,
  caption,
  aspect = "aspect-[4/3]",
}: {
  kind: FramedArtKind;
  caption?: string;
  aspect?: string;
}) {
  return (
    <figure
      className="evx-card-hover group relative overflow-hidden rounded-2xl border border-white/10 bg-navy-900 shadow-2xl shadow-black/50"
      data-framed-art={kind}
    >
      <div aria-hidden className={clsx("relative w-full overflow-hidden", aspect)}>
        <div className={`evx-art evx-art-${kind} absolute inset-0 transition-transform duration-700 ease-out group-hover:scale-[1.03]`} />
        <div className="evx-grain absolute inset-0" />
        <div className="absolute inset-0 bg-gradient-to-t from-navy-950/80 via-transparent to-transparent" />
      </div>
      {caption && (
        <figcaption className="absolute inset-x-0 bottom-0 px-4 pb-3 text-xs text-slate-300">{caption}</figcaption>
      )}
    </figure>
  );
}
