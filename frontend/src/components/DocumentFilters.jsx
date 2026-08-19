import OrbitInput from "./ui/OrbitInput";

/**
 * Toolbar filters for the Knowledge Library. Search, project filter and type
 * filter all compose client-side against already-loaded metadata.
 */
export default function DocumentFilters({
  search,
  onSearch,
  projectFilter,
  onProjectFilter,
  typeFilter,
  onTypeFilter,
  projects,
  types,
}) {
  return (
    <div className="doc-filters">
      <div className="doc-filters__search">
        <OrbitInput
          label="Search documents"
          placeholder="Search documents..."
          value={search}
          onChange={(e) => onSearch(e.target.value)}
          autoComplete="off"
          spellCheck="false"
        />
      </div>
      <div className="doc-filters__field">
        <span className="doc-filters__label" id="doc-filter-project-label">
          Project
        </span>
        <select
          className="orbit-input"
          aria-labelledby="doc-filter-project-label"
          value={projectFilter}
          onChange={(e) => onProjectFilter(e.target.value)}
        >
          <option value="">All projects</option>
          {projects.map((p) => (
            <option key={p.id} value={String(p.id)}>
              {p.name}
            </option>
          ))}
        </select>
      </div>
      <div className="doc-filters__field">
        <span className="doc-filters__label" id="doc-filter-type-label">
          Type
        </span>
        <select
          className="orbit-input"
          aria-labelledby="doc-filter-type-label"
          value={typeFilter}
          onChange={(e) => onTypeFilter(e.target.value)}
        >
          <option value="">All</option>
          {types.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}