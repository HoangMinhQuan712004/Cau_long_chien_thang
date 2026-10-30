import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";
import betterTailwindcss from "eslint-plugin-better-tailwindcss";

// Code giao diện mới viết theo prototype; code cũ chưa áp để diff gọn – thêm thư mục khi làm lại màn đó
const TAILWIND_CHECKED = [
  "src/components/ui/**/*.tsx",
  "src/app/(auth)/**/*.tsx",
  "src/app/admin/_components/**/*.tsx",
  "src/app/admin/hoi-vien/**/*.tsx",
];

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    // Kiểm class Tailwind: ngắt dòng chuỗi class dài, sắp xếp, báo class sai/trùng/đá nhau (`npm run lint -- --fix`)
    files: TAILWIND_CHECKED,
    extends: [betterTailwindcss.configs.recommended],
    settings: {
      "better-tailwindcss": { entryPoint: "src/app/globals.css" },
    },
    rules: {
      // Vừa 1 dòng thì giữ 1 dòng; dài hơn thì ngắt – chuỗi nhiều dòng phải đi qua cn() (lib/cn.ts)
      // để HTML ra một dòng gọn
      "better-tailwindcss/enforce-consistent-line-wrapping": [
        "warn",
        { printWidth: 100, preferSingleLine: true },
      ],
    },
  },
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
]);

export default eslintConfig;
