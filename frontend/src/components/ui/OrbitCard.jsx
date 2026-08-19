/**
 * OrbitCard — restrained surface primitive.
 *
 * `flush` removes the default padding for layouts that manage their own.
 */
export default function OrbitCard({
  as: Tag = "div",
  flush = false,
  className = "",
  children,
  ...rest
}) {
  return (
    <Tag
      className={["orbit-card", flush ? "orbit-card--flush" : "", className]
        .filter(Boolean)
        .join(" ")}
      {...rest}
    >
      {children}
    </Tag>
  );
}