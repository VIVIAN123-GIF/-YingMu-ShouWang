export function uniqueTextOptions(values) {
  const seen = new Set()
  return (values || []).filter((value) => {
    const text = String(value || '').trim()
    if (!text || seen.has(text)) return false
    seen.add(text)
    return true
  })
}

export function groupOptionsByLabel(entries, labelOf) {
  const groups = new Map()
  for (const [value, item] of Object.entries(entries || {})) {
    const label = labelOf(item, value)
    if (!label) continue
    const group = groups.get(label) || { label, value, values: [] }
    group.values.push(value)
    groups.set(label, group)
  }
  return [...groups.values()]
}

export function matchesGroupedOption(options, selectedValue, candidateValue) {
  if (!selectedValue) return true
  return (options.find((option) => option.value === selectedValue)?.values || [selectedValue]).includes(candidateValue)
}
