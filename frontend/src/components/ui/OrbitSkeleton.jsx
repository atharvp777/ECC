/**
 * OrbitSkeleton — shimmering placeholder that inherits Orbit surface tokens.
 *
 * Shapes: rect (default) | text | circle
 * Width/height are passed as inline style for layout flexibility.
 */
export default function OrbitSkeleton({
  width,
  height,
  shape = "rect",
  className = "",
  style = {},
  ...rest
}) {
  const shapeClass =
    shape === "circle"
      ? "orbit-skeleton--circle"
      : shape === "text"
        ? "orbit-skeleton--text"
        : "";

  return (
    <div
      className={["orbit-skeleton", shapeClass, className].filter(Boolean).join(" ")}
      style={{ width, height, ...style }}
      aria-hidden="true"
      {...rest}
    />
  );
}