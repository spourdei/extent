import eslint from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

const generatedPaths = [
  "**/.next/**",
  "**/.next-check/**",
  "**/next-env.d.ts",
  "apps/web/src/generated/**",
  "coverage/**",
  "node_modules/**",
];

const typedFiles = ["**/*.{ts,tsx}"];
const typedStrict = tseslint.configs.strictTypeChecked.map((config) => ({
  ...config,
  files: typedFiles,
}));
const typedStylistic = tseslint.configs.stylisticTypeChecked.map((config) => ({
  ...config,
  files: typedFiles,
}));

export default tseslint.config(
  { ignores: generatedPaths },
  eslint.configs.recommended,
  ...typedStrict,
  ...typedStylistic,
  {
    files: typedFiles,
    languageOptions: {
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
    rules: {
      "@typescript-eslint/consistent-type-exports": "error",
      "@typescript-eslint/consistent-type-imports": [
        "error",
        { fixStyle: "inline-type-imports" },
      ],
      "@typescript-eslint/no-explicit-any": "error",
      "@typescript-eslint/no-unnecessary-condition": "error",
    },
  },
  {
    files: ["apps/web/**/*.{ts,tsx}"],
    plugins: {
      "react-hooks": reactHooks,
    },
    rules: reactHooks.configs.recommended.rules,
  },
);
