/**
 * OrbitEmptyState — compact, actionable empty state.
 *
 * Props: icon (lucide component), title, description, action (React node).
 */
export default function OrbitEmptyState({
  icon: Icon,
  title,
  description,
  action,
  className = "",
  ...rest
}) {
  return (
    <div className={["orbit-empty", className].filter(Boolean).join(" ")} {...rest}>
      {Icon && <Icon className="orbit-empty__icon" size={28} strokeWidth={1.5} aria-hidden="true" />}
      {title && <div className="orbit-empty__title">{title}</div>}
      {description && <p className="orbit-empty__description">{description}</p>}
      {action && <div className="orbit-empty__action">{action}</div>}
    </div>
  );
}