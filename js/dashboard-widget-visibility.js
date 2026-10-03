export function filterVisibleWidgetKeys(keys, config = {}) {
  const visible = config?.visible || {};
  return [...keys].filter((key) => visible[key] !== false);
}
