import { forwardRef } from "react";

/**
 * OrbitButton — compact dark button primitive.
 *
 * Variants: primary | secondary (default) | ghost | danger
 * Sizes:    md (default) | sm
 */
const OrbitButton = forwardRef(function OrbitButton(
  {
    variant = "secondary",
    size = "md",
    loading = false,
    disabled = false,
    className = "",
    children,
    type = "button",
    ...rest
  },
  ref
) {
  const isDisabled = disabled || loading;
  const classes = [
    "orbit-btn",
    `orbit-btn--${variant}`,
    size === "sm" ? "orbit-btn--sm" : "",
    loading ? "orbit-btn--loading" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <button
      ref={ref}
      type={type}
      className={classes}
      disabled={isDisabled}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading && <span className="orbit-btn__spinner" aria-hidden="true" />}
      {children}
    </button>
  );
});

export default OrbitButton;