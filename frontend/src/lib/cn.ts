// Ghép class Tailwind, gộp khoảng trắng/xuống dòng để HTML ra một dòng
export function cn(...classes: Array<string | false | null | undefined>): string {
  return classes.filter(Boolean).join(" ").replace(/\s+/g, " ").trim();
}
