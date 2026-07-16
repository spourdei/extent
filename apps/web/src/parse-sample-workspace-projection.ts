import Ajv2020 from "ajv/dist/2020.js";
import addFormats from "ajv-formats";

import { extentApiSchema } from "./generated/extent-api-schema.ts";
import type { SampleWorkspaceProjection } from "./extent-api-contract.ts";

const ajv = new Ajv2020({ allErrors: true, strictSchema: false });
addFormats(ajv);

const validateSampleWorkspace = ajv.compile<SampleWorkspaceProjection>({
  $ref: "#/components/schemas/SampleWorkspaceProjection",
  components: extentApiSchema.components,
});

export const parseSampleWorkspaceProjection = (
  payload: unknown,
): SampleWorkspaceProjection => {
  if (validateSampleWorkspace(payload)) {
    return payload;
  }
  throw new Error("The API response did not satisfy the generated OpenAPI contract.");
};
