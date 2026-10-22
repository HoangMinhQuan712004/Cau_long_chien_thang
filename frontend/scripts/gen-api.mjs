// Sinh type TypeScript từ OpenAPI của backend: npm run gen:api
// Đổi nguồn: API_SCHEMA_URL=http://localhost:8001/api/v1/openapi.json npm run gen:api
import { execSync } from "node:child_process";

const url = process.env.API_SCHEMA_URL ?? "http://localhost:8000/api/v1/openapi.json";
execSync(`npx openapi-typescript ${url} -o src/lib/api/schema.d.ts`, { stdio: "inherit" });
