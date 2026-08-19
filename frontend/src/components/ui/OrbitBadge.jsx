/**
 * OrbitBadge — compact semantic label primitive.
 *
 * Variants: default | success | warning | danger | info | accent
 */
export default function OrbitBadge({
  variant = "default",
  className = "",
  children,
  ...rest
}) {
  return (
    <span
      className={["orbit-badge", `orbit-badge--${variant}`, className]
        .filter(Boolean)
        .join(" ")}
      {...rest}
    >
      {children}
    </span>
  );
}