// Photographic layers for the landing page. Files are pre-sized WebP in
// public/images/landing (see LANDING_IMAGES.md); the browser picks a width from
// srcset. Backgrounds are decorative: empty alt + aria-hidden, darkened by an overlay
// on the image layer only, never by opacity on the text above it.

import clsx from "clsx";

// Only images whose usage rights are cleared may be listed here. Photographs with
// unverified rights were removed and replaced by CSS artwork (backdrop.tsx).
export const LANDING_PHOTOS = {
  wall: [1920, 1280, 768],
} as const;

export type LandingPhoto = keyof typeof LANDING_PHOTOS;

export function photoSrcSet(name: LandingPhoto): string {
  return LANDING_PHOTOS[name].map((w) => `/images/landing/${name}-${w}.webp ${w}w`).join(", ");
}

export function photoSrc(name: LandingPhoto): string {
  const widths = LANDING_PHOTOS[name];
  return `/images/landing/${name}-${widths[widths.length - 1]}.webp`;
}

/** Full-bleed decorative photograph behind a section. `overlay` is applied on top of
 *  the image only; section text sits above both layers at full opacity. */
export function SectionPhoto({
  name,
  position,
  overlay,
  priority = false,
  className,
  imgClassName,
}: {
  name: LandingPhoto;
  /** CSS object-position; omit to position with a class instead. */
  position?: string;
  overlay: string;
  priority?: boolean;
  className?: string;
  /** Extra classes on the <img> itself, e.g. a mask that hides part of the photo. */
  imgClassName?: string;
}) {
  return (
    <div aria-hidden className={clsx("pointer-events-none absolute inset-0 -z-10 overflow-hidden", className)} data-photo={name}>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={photoSrc(name)}
        srcSet={photoSrcSet(name)}
        sizes="100vw"
        alt=""
        loading={priority ? "eager" : "lazy"}
        decoding="async"
        className={clsx("evx-photo h-full w-full object-cover", imgClassName)}
        // No position given: the browser default (centre) or a class (imgClassName) decides.
        style={position ? { objectPosition: position } : undefined}
      />
      <div className={clsx("absolute inset-0", overlay)} />
      {/* Fade into the page colour at the top and bottom so sections blend, not cut. */}
      <div className="absolute inset-0 bg-[linear-gradient(to_bottom,#0a0f1a_0%,transparent_16%,transparent_84%,#0a0f1a_100%)]" />
      <div className="evx-grain absolute inset-0" />
    </div>
  );
}

/** A framed photograph placed beside text. Meaningful, so it carries alt text. */
export function FramedPhoto({
  name,
  alt,
  caption,
  position = "center",
  aspect = "aspect-[4/3]",
  sizes = "(min-width: 1024px) 28rem, 90vw",
}: {
  name: LandingPhoto;
  alt: string;
  caption?: string;
  position?: string;
  aspect?: string;
  sizes?: string;
}) {
  return (
    <figure className="evx-card-hover group relative overflow-hidden rounded-2xl border border-white/10 bg-navy-900 shadow-2xl shadow-black/50">
      <div className={clsx("relative w-full overflow-hidden", aspect)}>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={photoSrc(name)}
          srcSet={photoSrcSet(name)}
          sizes={sizes}
          alt={alt}
          loading="lazy"
          decoding="async"
          className="evx-photo absolute inset-0 h-full w-full object-cover transition-transform duration-700 ease-out group-hover:scale-[1.03]"
          style={{ objectPosition: position }}
          data-photo={name}
        />
        <div aria-hidden className="absolute inset-0 bg-gradient-to-t from-navy-950/80 via-transparent to-transparent" />
      </div>
      {caption && (
        <figcaption className="absolute inset-x-0 bottom-0 px-4 pb-3 text-xs text-slate-300">{caption}</figcaption>
      )}
    </figure>
  );
}
