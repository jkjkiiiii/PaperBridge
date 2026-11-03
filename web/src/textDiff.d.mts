export type DisplayChange = { value: string; added?: boolean; removed?: boolean; count?: number };
export function englishDisplayDiff(before: string, after: string): DisplayChange[];
export function isInflectionPair(before: string, after: string): boolean;
