function hasExplicitTimezone(value: string): boolean {
  return /(?:[zZ]|[+-]\d{2}:\d{2})$/.test(value);
}

export function parseServerDate(value: string): Date {
  const normalized = hasExplicitTimezone(value) ? value : `${value}Z`;
  return new Date(normalized);
}
