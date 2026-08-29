export const DEFAULT_ACTIVITY_HEATMAP = Object.freeze({
  days: ['07-18', '07-19', '07-20', '07-21', '07-22', '07-23', '07-24'],
  periods: ['夜间', '傍晚', '白天', '清晨'],
  matrix: [
    [25, 24, 21, 19, 17, 16, 18],
    [61, 58, 52, 45, 42, 39, 44],
    [72, 68, 61, 53, 49, 46, 52],
    [50, 48, 43, 37, 34, 32, 36],
  ],
})

export function normalizeActivityHeatmap(source = DEFAULT_ACTIVITY_HEATMAP) {
  const days = source.days?.length ? source.days : DEFAULT_ACTIVITY_HEATMAP.days
  const periods = source.periods?.length ? source.periods : DEFAULT_ACTIVITY_HEATMAP.periods
  const values = source.values?.length
    ? source.values
    : (source.matrix || DEFAULT_ACTIVITY_HEATMAP.matrix).flatMap((row, y) => row.map((value, x) => [x, y, value]))
  return { days, periods, values }
}
