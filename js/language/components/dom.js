export function node(tag, options = {}, children = []) {
  const element = document.createElement(tag);
  if (options.className) element.className = options.className;
  if (options.text !== undefined) element.textContent = String(options.text);
  if (options.id) element.id = options.id;
  if (options.type) element.type = options.type;
  if (options.value !== undefined) element.value = String(options.value);
  if (options.name) element.name = options.name;
  if (options.placeholder) element.placeholder = options.placeholder;
  if (options.disabled) element.disabled = true;
  if (options.hidden) element.hidden = true;
  if (options.attrs) {
    Object.entries(options.attrs).forEach(([name, value]) => {
      if (value !== null && value !== undefined) element.setAttribute(name, String(value));
    });
  }
  if (options.dataset) Object.assign(element.dataset, options.dataset);
  const list = Array.isArray(children) ? children : [children];
  list.filter((child) => child !== null && child !== undefined).forEach((child) => {
    element.append(child instanceof Node ? child : document.createTextNode(String(child)));
  });
  return element;
}

export function replace(mount, ...children) {
  mount.replaceChildren(...children.filter(Boolean));
}

export function statusPill(label, tone = 'muted') {
  return node('span', { className: 'language-status', text: label, attrs: { 'data-tone': tone } });
}

export function sectionHeading(title, description) {
  return node('div', { className: 'language-section-head' }, [
    node('div', {}, [node('h3', { text: title }), description ? node('p', { text: description }) : null]),
  ]);
}

export function messageState(kind, title, detail) {
  return node('div', { className: `language-${kind}` }, [
    node('div', {}, [node('strong', { text: title }), detail ? node('div', { text: detail }) : null]),
  ]);
}

export function field(label, control) {
  return node('label', { className: 'language-field' }, [node('span', { text: label }), control]);
}

export function selectControl(name, options, value = '') {
  const select = node('select', { name });
  options.forEach((option) => {
    const item = typeof option === 'string' ? { value: option, label: option } : option;
    const optionNode = node('option', { value: item.value, text: item.label });
    select.append(optionNode);
  });
  select.value = String(value ?? '');
  return select;
}

export function definitionList(entries, className = '') {
  const list = node('dl', { className });
  entries.forEach(([term, value]) => {
    list.append(node('dt', { text: term }), node('dd', { text: value ?? '—' }));
  });
  return list;
}
