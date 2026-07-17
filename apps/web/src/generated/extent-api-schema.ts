/**
 * This file is generated from the checked-in FastAPI OpenAPI document.
 * Do not edit it directly; run `pnpm openapi:generate`.
 */
export const extentApiSchema = {
  "components": {
    "schemas": {
      "Applicability": {
        "additionalProperties": false,
        "properties": {
          "effectiveFrom": {
            "anyOf": [
              {
                "format": "date",
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "title": "Effectivefrom"
          },
          "effectiveTo": {
            "anyOf": [
              {
                "format": "date",
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "title": "Effectiveto"
          },
          "entity": {
            "maxLength": 160,
            "minLength": 1,
            "title": "Entity",
            "type": "string"
          },
          "field": {
            "maxLength": 120,
            "minLength": 1,
            "title": "Field",
            "type": "string"
          },
          "periodLabel": {
            "maxLength": 120,
            "minLength": 1,
            "title": "Periodlabel",
            "type": "string"
          },
          "scope": {
            "maxLength": 240,
            "minLength": 1,
            "title": "Scope",
            "type": "string"
          }
        },
        "required": [
          "effectiveFrom",
          "effectiveTo",
          "entity",
          "field",
          "periodLabel",
          "scope"
        ],
        "title": "Applicability",
        "type": "object"
      },
      "AskWorkspaceQuestionRequest": {
        "additionalProperties": false,
        "properties": {
          "question": {
            "maxLength": 2000,
            "minLength": 3,
            "title": "Question",
            "type": "string"
          }
        },
        "required": [
          "question"
        ],
        "title": "AskWorkspaceQuestionRequest",
        "type": "object"
      },
      "AuthErrorView": {
        "additionalProperties": false,
        "properties": {
          "code": {
            "enum": [
              "configuration_unavailable",
              "origin_rejected"
            ],
            "title": "Code",
            "type": "string"
          },
          "message": {
            "maxLength": 280,
            "minLength": 1,
            "title": "Message",
            "type": "string"
          }
        },
        "required": [
          "code",
          "message"
        ],
        "title": "AuthErrorView",
        "type": "object"
      },
      "AuthenticatedSessionView": {
        "additionalProperties": false,
        "properties": {
          "account": {
            "$ref": "#/components/schemas/GoogleAccountView"
          },
          "expiresAt": {
            "format": "date-time",
            "title": "Expiresat",
            "type": "string"
          },
          "googleOauthAvailable": {
            "const": true,
            "default": true,
            "title": "Googleoauthavailable",
            "type": "boolean"
          },
          "status": {
            "const": "authenticated",
            "default": "authenticated",
            "title": "Status",
            "type": "string"
          }
        },
        "required": [
          "account",
          "expiresAt"
        ],
        "title": "AuthenticatedSessionView",
        "type": "object"
      },
      "Citation": {
        "additionalProperties": false,
        "properties": {
          "citationId": {
            "format": "uuid",
            "title": "Citationid",
            "type": "string"
          },
          "documentVersionId": {
            "format": "uuid",
            "title": "Documentversionid",
            "type": "string"
          },
          "locator": {
            "discriminator": {
              "mapping": {
                "pdf_page": "#/components/schemas/PdfPageLocator",
                "text_lines": "#/components/schemas/TextLineLocator"
              },
              "propertyName": "kind"
            },
            "oneOf": [
              {
                "$ref": "#/components/schemas/TextLineLocator"
              },
              {
                "$ref": "#/components/schemas/PdfPageLocator"
              }
            ],
            "title": "Locator"
          },
          "quote": {
            "maxLength": 2000,
            "minLength": 1,
            "title": "Quote",
            "type": "string"
          },
          "sourceBlockId": {
            "format": "uuid",
            "title": "Sourceblockid",
            "type": "string"
          }
        },
        "required": [
          "citationId",
          "documentVersionId",
          "locator",
          "quote",
          "sourceBlockId"
        ],
        "title": "Citation",
        "type": "object"
      },
      "CitationContext": {
        "additionalProperties": false,
        "properties": {
          "citationId": {
            "format": "uuid",
            "title": "Citationid",
            "type": "string"
          },
          "fileName": {
            "maxLength": 240,
            "minLength": 1,
            "title": "Filename",
            "type": "string"
          },
          "locatorLabel": {
            "maxLength": 80,
            "minLength": 1,
            "title": "Locatorlabel",
            "type": "string"
          },
          "observedAt": {
            "format": "date-time",
            "title": "Observedat",
            "type": "string"
          },
          "passageAfter": {
            "maxLength": 221,
            "title": "Passageafter",
            "type": "string"
          },
          "passageBefore": {
            "maxLength": 221,
            "title": "Passagebefore",
            "type": "string"
          }
        },
        "required": [
          "citationId",
          "fileName",
          "locatorLabel",
          "observedAt",
          "passageAfter",
          "passageBefore"
        ],
        "title": "CitationContext",
        "type": "object"
      },
      "ContextManifest": {
        "additionalProperties": false,
        "properties": {
          "activeClaimIds": {
            "items": {
              "format": "uuid",
              "type": "string"
            },
            "maxItems": 12,
            "title": "Activeclaimids",
            "type": "array"
          },
          "activeTurnIds": {
            "items": {
              "format": "uuid",
              "type": "string"
            },
            "maxItems": 4,
            "title": "Activeturnids",
            "type": "array"
          },
          "candidateChunkIds": {
            "items": {
              "format": "uuid",
              "type": "string"
            },
            "maxItems": 40,
            "title": "Candidatechunkids",
            "type": "array"
          },
          "contextPolicyVersion": {
            "maxLength": 80,
            "minLength": 1,
            "title": "Contextpolicyversion",
            "type": "string"
          },
          "excludedChunks": {
            "items": {
              "$ref": "#/components/schemas/ExcludedContextChunk"
            },
            "maxItems": 40,
            "title": "Excludedchunks",
            "type": "array"
          },
          "includedChunkIds": {
            "items": {
              "format": "uuid",
              "type": "string"
            },
            "maxItems": 12,
            "title": "Includedchunkids",
            "type": "array"
          },
          "originalMessageHash": {
            "pattern": "^[a-f0-9]{64}$",
            "title": "Originalmessagehash",
            "type": "string"
          },
          "selectionOrdering": {
            "const": "retrieval_rank_then_source_cap",
            "title": "Selectionordering",
            "type": "string"
          },
          "snapshotId": {
            "format": "uuid",
            "title": "Snapshotid",
            "type": "string"
          },
          "sourceCounts": {
            "items": {
              "$ref": "#/components/schemas/ContextSourceCount"
            },
            "maxItems": 40,
            "title": "Sourcecounts",
            "type": "array"
          },
          "tokenBudget": {
            "exclusiveMinimum": 0.0,
            "maximum": 16000.0,
            "title": "Tokenbudget",
            "type": "integer"
          }
        },
        "required": [
          "activeClaimIds",
          "activeTurnIds",
          "candidateChunkIds",
          "contextPolicyVersion",
          "excludedChunks",
          "includedChunkIds",
          "originalMessageHash",
          "selectionOrdering",
          "snapshotId",
          "sourceCounts",
          "tokenBudget"
        ],
        "title": "ContextManifest",
        "type": "object"
      },
      "ContextSourceCount": {
        "additionalProperties": false,
        "properties": {
          "candidateChunkCount": {
            "minimum": 0.0,
            "title": "Candidatechunkcount",
            "type": "integer"
          },
          "documentVersionId": {
            "format": "uuid",
            "title": "Documentversionid",
            "type": "string"
          },
          "includedChunkCount": {
            "minimum": 0.0,
            "title": "Includedchunkcount",
            "type": "integer"
          }
        },
        "required": [
          "candidateChunkCount",
          "documentVersionId",
          "includedChunkCount"
        ],
        "title": "ContextSourceCount",
        "type": "object"
      },
      "CoverageManifest": {
        "additionalProperties": false,
        "properties": {
          "capped": {
            "minimum": 0.0,
            "title": "Capped",
            "type": "integer"
          },
          "discovered": {
            "minimum": 0.0,
            "title": "Discovered",
            "type": "integer"
          },
          "discoveryComplete": {
            "title": "Discoverycomplete",
            "type": "boolean"
          },
          "failed": {
            "minimum": 0.0,
            "title": "Failed",
            "type": "integer"
          },
          "gapReasons": {
            "items": {
              "enum": [
                "processing",
                "failed",
                "unsupported",
                "inaccessible",
                "capped",
                "unknown_branch",
                "unstable",
                "unsafe_to_parse"
              ],
              "type": "string"
            },
            "title": "Gapreasons",
            "type": "array"
          },
          "inaccessible": {
            "minimum": 0.0,
            "title": "Inaccessible",
            "type": "integer"
          },
          "processing": {
            "minimum": 0.0,
            "title": "Processing",
            "type": "integer"
          },
          "ready": {
            "minimum": 0.0,
            "title": "Ready",
            "type": "integer"
          },
          "unknownBranches": {
            "minimum": 0.0,
            "title": "Unknownbranches",
            "type": "integer"
          },
          "unsafeToParse": {
            "minimum": 0.0,
            "title": "Unsafetoparse",
            "type": "integer"
          },
          "unstable": {
            "minimum": 0.0,
            "title": "Unstable",
            "type": "integer"
          },
          "unsupported": {
            "minimum": 0.0,
            "title": "Unsupported",
            "type": "integer"
          }
        },
        "required": [
          "capped",
          "discovered",
          "discoveryComplete",
          "failed",
          "gapReasons",
          "inaccessible",
          "processing",
          "ready",
          "unsafeToParse",
          "unknownBranches",
          "unstable",
          "unsupported"
        ],
        "title": "CoverageManifest",
        "type": "object"
      },
      "CreateWorkspaceRequest": {
        "additionalProperties": false,
        "properties": {
          "folderUrl": {
            "maxLength": 2048,
            "minLength": 1,
            "title": "Folderurl",
            "type": "string"
          }
        },
        "required": [
          "folderUrl"
        ],
        "title": "CreateWorkspaceRequest",
        "type": "object"
      },
      "EvidenceFunnel": {
        "additionalProperties": false,
        "properties": {
          "candidateBlockIds": {
            "items": {
              "format": "uuid",
              "type": "string"
            },
            "maxItems": 40,
            "title": "Candidateblockids",
            "type": "array"
          },
          "eligibleClaimIds": {
            "items": {
              "format": "uuid",
              "type": "string"
            },
            "maxItems": 12,
            "title": "Eligibleclaimids",
            "type": "array"
          },
          "excludedEvidence": {
            "items": {
              "$ref": "#/components/schemas/ExcludedEvidence"
            },
            "maxItems": 40,
            "title": "Excludedevidence",
            "type": "array"
          },
          "includedBlockIds": {
            "items": {
              "format": "uuid",
              "type": "string"
            },
            "maxItems": 12,
            "title": "Includedblockids",
            "type": "array"
          },
          "proposedClaims": {
            "items": {
              "$ref": "#/components/schemas/ProposedClaimRef"
            },
            "maxItems": 12,
            "title": "Proposedclaims",
            "type": "array"
          },
          "publishedClaimIds": {
            "items": {
              "format": "uuid",
              "type": "string"
            },
            "maxItems": 12,
            "title": "Publishedclaimids",
            "type": "array"
          },
          "suppressedClaims": {
            "items": {
              "$ref": "#/components/schemas/SuppressedClaimRef"
            },
            "maxItems": 12,
            "title": "Suppressedclaims",
            "type": "array"
          },
          "verifierVerdicts": {
            "items": {
              "$ref": "#/components/schemas/VerifierVerdict"
            },
            "maxItems": 12,
            "title": "Verifierverdicts",
            "type": "array"
          }
        },
        "required": [
          "candidateBlockIds",
          "eligibleClaimIds",
          "excludedEvidence",
          "includedBlockIds",
          "proposedClaims",
          "publishedClaimIds",
          "suppressedClaims",
          "verifierVerdicts"
        ],
        "title": "EvidenceFunnel",
        "type": "object"
      },
      "ExcludedContextChunk": {
        "additionalProperties": false,
        "properties": {
          "chunkId": {
            "format": "uuid",
            "title": "Chunkid",
            "type": "string"
          },
          "reasonCode": {
            "maxLength": 80,
            "minLength": 1,
            "title": "Reasoncode",
            "type": "string"
          }
        },
        "required": [
          "chunkId",
          "reasonCode"
        ],
        "title": "ExcludedContextChunk",
        "type": "object"
      },
      "ExcludedEvidence": {
        "additionalProperties": false,
        "properties": {
          "reasonCode": {
            "maxLength": 80,
            "minLength": 1,
            "title": "Reasoncode",
            "type": "string"
          },
          "sourceBlockId": {
            "format": "uuid",
            "title": "Sourceblockid",
            "type": "string"
          }
        },
        "required": [
          "reasonCode",
          "sourceBlockId"
        ],
        "title": "ExcludedEvidence",
        "type": "object"
      },
      "ExtentRevision": {
        "additionalProperties": false,
        "properties": {
          "coverage": {
            "$ref": "#/components/schemas/CoverageManifest"
          },
          "freshness": {
            "$ref": "#/components/schemas/Freshness"
          },
          "observedVersionCount": {
            "minimum": 0.0,
            "title": "Observedversioncount",
            "type": "integer"
          },
          "snapshotId": {
            "format": "uuid",
            "title": "Snapshotid",
            "type": "string"
          },
          "syncEndedAt": {
            "format": "date-time",
            "title": "Syncendedat",
            "type": "string"
          },
          "syncStartedAt": {
            "format": "date-time",
            "title": "Syncstartedat",
            "type": "string"
          }
        },
        "required": [
          "coverage",
          "freshness",
          "observedVersionCount",
          "snapshotId",
          "syncEndedAt",
          "syncStartedAt"
        ],
        "title": "ExtentRevision",
        "type": "object"
      },
      "ExtractedLineage": {
        "additionalProperties": false,
        "properties": {
          "applicability": {
            "$ref": "#/components/schemas/Applicability"
          },
          "citationIds": {
            "items": {
              "format": "uuid",
              "type": "string"
            },
            "maxItems": 12,
            "minItems": 1,
            "title": "Citationids",
            "type": "array"
          },
          "documentVersionId": {
            "format": "uuid",
            "title": "Documentversionid",
            "type": "string"
          },
          "kind": {
            "const": "extracted",
            "title": "Kind",
            "type": "string"
          },
          "normalizedValue": {
            "$ref": "#/components/schemas/MoneyValue"
          }
        },
        "required": [
          "applicability",
          "citationIds",
          "documentVersionId",
          "kind",
          "normalizedValue"
        ],
        "title": "ExtractedLineage",
        "type": "object"
      },
      "Freshness": {
        "additionalProperties": false,
        "properties": {
          "checkedAt": {
            "format": "date-time",
            "title": "Checkedat",
            "type": "string"
          },
          "status": {
            "enum": [
              "fresh",
              "refreshing",
              "stale",
              "unknown"
            ],
            "title": "Status",
            "type": "string"
          }
        },
        "required": [
          "checkedAt",
          "status"
        ],
        "title": "Freshness",
        "type": "object"
      },
      "GoogleAccountView": {
        "additionalProperties": false,
        "properties": {
          "displayName": {
            "anyOf": [
              {
                "maxLength": 200,
                "minLength": 1,
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "title": "Displayname"
          },
          "email": {
            "maxLength": 320,
            "minLength": 3,
            "title": "Email",
            "type": "string"
          }
        },
        "required": [
          "displayName",
          "email"
        ],
        "title": "GoogleAccountView",
        "type": "object"
      },
      "HTTPValidationError": {
        "properties": {
          "detail": {
            "items": {
              "$ref": "#/components/schemas/ValidationError"
            },
            "title": "Detail",
            "type": "array"
          }
        },
        "title": "HTTPValidationError",
        "type": "object"
      },
      "HealthResponse": {
        "additionalProperties": false,
        "properties": {
          "service": {
            "const": "extent-api",
            "default": "extent-api",
            "title": "Service",
            "type": "string"
          },
          "status": {
            "const": "ok",
            "default": "ok",
            "title": "Status",
            "type": "string"
          },
          "version": {
            "title": "Version",
            "type": "string"
          }
        },
        "required": [
          "version"
        ],
        "title": "HealthResponse",
        "type": "object"
      },
      "MoneyValue": {
        "additionalProperties": false,
        "properties": {
          "currency": {
            "pattern": "^[A-Z]{3}$",
            "title": "Currency",
            "type": "string"
          },
          "kind": {
            "const": "money",
            "title": "Kind",
            "type": "string"
          },
          "literal": {
            "maxLength": 120,
            "minLength": 1,
            "title": "Literal",
            "type": "string"
          },
          "valueMinor": {
            "pattern": "^-?(?:0|[1-9]\\d*)$",
            "title": "Valueminor",
            "type": "string"
          }
        },
        "required": [
          "currency",
          "kind",
          "literal",
          "valueMinor"
        ],
        "title": "MoneyValue",
        "type": "object"
      },
      "PdfPageLocator": {
        "additionalProperties": false,
        "properties": {
          "kind": {
            "const": "pdf_page",
            "title": "Kind",
            "type": "string"
          },
          "normalizedEndExclusive": {
            "minimum": 0.0,
            "title": "Normalizedendexclusive",
            "type": "integer"
          },
          "normalizedStart": {
            "minimum": 0.0,
            "title": "Normalizedstart",
            "type": "integer"
          },
          "pageIndexZeroBased": {
            "minimum": 0.0,
            "title": "Pageindexzerobased",
            "type": "integer"
          },
          "printedPageLabel": {
            "anyOf": [
              {
                "maxLength": 40,
                "minLength": 1,
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "title": "Printedpagelabel"
          },
          "rawEndExclusive": {
            "minimum": 0.0,
            "title": "Rawendexclusive",
            "type": "integer"
          },
          "rawStart": {
            "minimum": 0.0,
            "title": "Rawstart",
            "type": "integer"
          }
        },
        "required": [
          "normalizedEndExclusive",
          "normalizedStart",
          "rawEndExclusive",
          "rawStart",
          "kind",
          "pageIndexZeroBased",
          "printedPageLabel"
        ],
        "title": "PdfPageLocator",
        "type": "object"
      },
      "ProposedClaimRef": {
        "additionalProperties": false,
        "properties": {
          "citedBlockIds": {
            "items": {
              "format": "uuid",
              "type": "string"
            },
            "maxItems": 12,
            "minItems": 1,
            "title": "Citedblockids",
            "type": "array"
          },
          "claimId": {
            "format": "uuid",
            "title": "Claimid",
            "type": "string"
          }
        },
        "required": [
          "citedBlockIds",
          "claimId"
        ],
        "title": "ProposedClaimRef",
        "type": "object"
      },
      "PublishedAnswerView": {
        "additionalProperties": false,
        "properties": {
          "answerId": {
            "format": "uuid",
            "title": "Answerid",
            "type": "string"
          },
          "citations": {
            "items": {
              "$ref": "#/components/schemas/Citation"
            },
            "maxItems": 6,
            "minItems": 1,
            "title": "Citations",
            "type": "array"
          },
          "claims": {
            "items": {
              "$ref": "#/components/schemas/PublishedClaim"
            },
            "maxItems": 3,
            "minItems": 1,
            "title": "Claims",
            "type": "array"
          },
          "funnel": {
            "$ref": "#/components/schemas/EvidenceFunnel"
          },
          "revision": {
            "$ref": "#/components/schemas/ExtentRevision"
          },
          "terminal": {
            "$ref": "#/components/schemas/PublishedTerminal"
          },
          "traceId": {
            "format": "uuid",
            "title": "Traceid",
            "type": "string"
          }
        },
        "required": [
          "answerId",
          "citations",
          "claims",
          "funnel",
          "revision",
          "terminal",
          "traceId"
        ],
        "title": "PublishedAnswerView",
        "type": "object"
      },
      "PublishedClaim": {
        "additionalProperties": false,
        "properties": {
          "citationIds": {
            "items": {
              "format": "uuid",
              "type": "string"
            },
            "maxItems": 12,
            "minItems": 1,
            "title": "Citationids",
            "type": "array"
          },
          "claimId": {
            "format": "uuid",
            "title": "Claimid",
            "type": "string"
          },
          "kind": {
            "const": "extracted",
            "title": "Kind",
            "type": "string"
          },
          "lineage": {
            "$ref": "#/components/schemas/ExtractedLineage"
          },
          "relationKind": {
            "const": "fact",
            "title": "Relationkind",
            "type": "string"
          },
          "status": {
            "const": "published",
            "title": "Status",
            "type": "string"
          },
          "text": {
            "maxLength": 800,
            "minLength": 1,
            "title": "Text",
            "type": "string"
          }
        },
        "required": [
          "claimId",
          "kind",
          "lineage",
          "relationKind",
          "text",
          "citationIds",
          "status"
        ],
        "title": "PublishedClaim",
        "type": "object"
      },
      "PublishedTerminal": {
        "additionalProperties": false,
        "properties": {
          "answerId": {
            "format": "uuid",
            "title": "Answerid",
            "type": "string"
          },
          "status": {
            "enum": [
              "evidence_supported",
              "changed",
              "conflict",
              "not_comparable",
              "precedence_unknown"
            ],
            "title": "Status",
            "type": "string"
          },
          "terminalAt": {
            "format": "date-time",
            "title": "Terminalat",
            "type": "string"
          },
          "traceId": {
            "format": "uuid",
            "title": "Traceid",
            "type": "string"
          }
        },
        "required": [
          "terminalAt",
          "traceId",
          "answerId",
          "status"
        ],
        "title": "PublishedTerminal",
        "type": "object"
      },
      "QueryExecution": {
        "additionalProperties": false,
        "properties": {
          "acknowledgementCopyKey": {
            "const": "evidence_acknowledgement",
            "title": "Acknowledgementcopykey",
            "type": "string"
          },
          "contextManifest": {
            "anyOf": [
              {
                "$ref": "#/components/schemas/ContextManifest"
              },
              {
                "type": "null"
              }
            ]
          },
          "replayed": {
            "title": "Replayed",
            "type": "boolean"
          },
          "stages": {
            "items": {
              "enum": [
                "accepted",
                "authorizing",
                "interpreting",
                "cache_check",
                "contextualizing",
                "retrieving",
                "composing",
                "structural_validation",
                "verifying",
                "publishing",
                "complete"
              ],
              "type": "string"
            },
            "maxItems": 11,
            "minItems": 3,
            "title": "Stages",
            "type": "array"
          },
          "view": {
            "$ref": "#/components/schemas/PublishedAnswerView"
          }
        },
        "required": [
          "acknowledgementCopyKey",
          "contextManifest",
          "replayed",
          "stages",
          "view"
        ],
        "title": "QueryExecution",
        "type": "object"
      },
      "SampleWorkspaceProjection": {
        "additionalProperties": false,
        "properties": {
          "citationContexts": {
            "items": {
              "$ref": "#/components/schemas/CitationContext"
            },
            "maxItems": 6,
            "title": "Citationcontexts",
            "type": "array"
          },
          "execution": {
            "$ref": "#/components/schemas/QueryExecution"
          },
          "question": {
            "maxLength": 1000,
            "minLength": 1,
            "title": "Question",
            "type": "string"
          },
          "workspace": {
            "$ref": "#/components/schemas/WorkspaceSummary"
          }
        },
        "required": [
          "citationContexts",
          "execution",
          "question",
          "workspace"
        ],
        "title": "SampleWorkspaceProjection",
        "type": "object"
      },
      "SignedOutSessionView": {
        "additionalProperties": false,
        "properties": {
          "googleOauthAvailable": {
            "title": "Googleoauthavailable",
            "type": "boolean"
          },
          "status": {
            "const": "signed_out",
            "default": "signed_out",
            "title": "Status",
            "type": "string"
          }
        },
        "required": [
          "googleOauthAvailable"
        ],
        "title": "SignedOutSessionView",
        "type": "object"
      },
      "SuppressedClaimRef": {
        "additionalProperties": false,
        "properties": {
          "claimId": {
            "format": "uuid",
            "title": "Claimid",
            "type": "string"
          },
          "reasonCode": {
            "maxLength": 80,
            "minLength": 1,
            "title": "Reasoncode",
            "type": "string"
          }
        },
        "required": [
          "claimId",
          "reasonCode"
        ],
        "title": "SuppressedClaimRef",
        "type": "object"
      },
      "TextLineLocator": {
        "additionalProperties": false,
        "properties": {
          "kind": {
            "const": "text_lines",
            "title": "Kind",
            "type": "string"
          },
          "lineEndOneBasedInclusive": {
            "exclusiveMinimum": 0.0,
            "title": "Lineendonebasedinclusive",
            "type": "integer"
          },
          "lineStartOneBased": {
            "exclusiveMinimum": 0.0,
            "title": "Linestartonebased",
            "type": "integer"
          },
          "normalizedEndExclusive": {
            "minimum": 0.0,
            "title": "Normalizedendexclusive",
            "type": "integer"
          },
          "normalizedStart": {
            "minimum": 0.0,
            "title": "Normalizedstart",
            "type": "integer"
          },
          "rawEndExclusive": {
            "minimum": 0.0,
            "title": "Rawendexclusive",
            "type": "integer"
          },
          "rawStart": {
            "minimum": 0.0,
            "title": "Rawstart",
            "type": "integer"
          }
        },
        "required": [
          "normalizedEndExclusive",
          "normalizedStart",
          "rawEndExclusive",
          "rawStart",
          "kind",
          "lineEndOneBasedInclusive",
          "lineStartOneBased"
        ],
        "title": "TextLineLocator",
        "type": "object"
      },
      "ValidationError": {
        "properties": {
          "ctx": {
            "title": "Context",
            "type": "object"
          },
          "input": {
            "title": "Input"
          },
          "loc": {
            "items": {
              "anyOf": [
                {
                  "type": "string"
                },
                {
                  "type": "integer"
                }
              ]
            },
            "title": "Location",
            "type": "array"
          },
          "msg": {
            "title": "Message",
            "type": "string"
          },
          "type": {
            "title": "Error Type",
            "type": "string"
          }
        },
        "required": [
          "loc",
          "msg",
          "type"
        ],
        "title": "ValidationError",
        "type": "object"
      },
      "VerifierVerdict": {
        "additionalProperties": false,
        "properties": {
          "claimId": {
            "format": "uuid",
            "title": "Claimid",
            "type": "string"
          },
          "verdict": {
            "enum": [
              "supported",
              "partial",
              "unsupported",
              "contradicted"
            ],
            "title": "Verdict",
            "type": "string"
          }
        },
        "required": [
          "claimId",
          "verdict"
        ],
        "title": "VerifierVerdict",
        "type": "object"
      },
      "WorkspaceApprovedClaimView": {
        "additionalProperties": false,
        "properties": {
          "citations": {
            "items": {
              "$ref": "#/components/schemas/WorkspaceEvidencePassageView"
            },
            "maxItems": 2,
            "minItems": 1,
            "title": "Citations",
            "type": "array"
          },
          "claimId": {
            "format": "uuid",
            "title": "Claimid",
            "type": "string"
          },
          "relation": {
            "enum": [
              "fact",
              "change",
              "conflict",
              "unclear"
            ],
            "title": "Relation",
            "type": "string"
          },
          "text": {
            "maxLength": 800,
            "minLength": 1,
            "title": "Text",
            "type": "string"
          },
          "value": {
            "anyOf": [
              {
                "maxLength": 120,
                "minLength": 1,
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "title": "Value"
          }
        },
        "required": [
          "citations",
          "claimId",
          "relation",
          "text",
          "value"
        ],
        "title": "WorkspaceApprovedClaimView",
        "type": "object"
      },
      "WorkspaceErrorView": {
        "additionalProperties": false,
        "properties": {
          "code": {
            "enum": [
              "authentication_required",
              "idempotency_conflict",
              "invalid_folder_url",
              "origin_rejected",
              "rate_limit_unavailable",
              "rate_limited",
              "retrieval_unavailable",
              "workspace_not_retryable",
              "workspace_not_ready",
              "workspace_not_found"
            ],
            "title": "Code",
            "type": "string"
          },
          "message": {
            "maxLength": 280,
            "minLength": 1,
            "title": "Message",
            "type": "string"
          },
          "reasonCode": {
            "anyOf": [
              {
                "maxLength": 80,
                "minLength": 1,
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "title": "Reasoncode"
          }
        },
        "required": [
          "code",
          "message"
        ],
        "title": "WorkspaceErrorView",
        "type": "object"
      },
      "WorkspaceEvidencePassageView": {
        "additionalProperties": false,
        "properties": {
          "blockId": {
            "format": "uuid",
            "title": "Blockid",
            "type": "string"
          },
          "driveFileId": {
            "maxLength": 200,
            "minLength": 1,
            "pattern": "^[A-Za-z0-9_-]+$",
            "title": "Drivefileid",
            "type": "string"
          },
          "endExclusiveInBlock": {
            "exclusiveMinimum": 0.0,
            "title": "Endexclusiveinblock",
            "type": "integer"
          },
          "exactQuote": {
            "maxLength": 2000,
            "minLength": 1,
            "title": "Exactquote",
            "type": "string"
          },
          "lineStartOneBased": {
            "anyOf": [
              {
                "exclusiveMinimum": 0.0,
                "type": "integer"
              },
              {
                "type": "null"
              }
            ],
            "title": "Linestartonebased"
          },
          "normalizedValue": {
            "anyOf": [
              {
                "maxLength": 120,
                "minLength": 1,
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "title": "Normalizedvalue"
          },
          "originKind": {
            "enum": [
              "pdf_page",
              "text_lines"
            ],
            "title": "Originkind",
            "type": "string"
          },
          "pageIndexZeroBased": {
            "anyOf": [
              {
                "minimum": 0.0,
                "type": "integer"
              },
              {
                "type": "null"
              }
            ],
            "title": "Pageindexzerobased"
          },
          "path": {
            "items": {
              "maxLength": 1024,
              "minLength": 1,
              "type": "string"
            },
            "maxItems": 8,
            "minItems": 2,
            "title": "Path",
            "type": "array"
          },
          "printedPageLabel": {
            "anyOf": [
              {
                "maxLength": 40,
                "minLength": 1,
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "title": "Printedpagelabel"
          },
          "rawValue": {
            "anyOf": [
              {
                "maxLength": 120,
                "minLength": 1,
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "title": "Rawvalue"
          },
          "role": {
            "anyOf": [
              {
                "enum": [
                  "support",
                  "before",
                  "after",
                  "left",
                  "right"
                ],
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "title": "Role"
          },
          "sourceName": {
            "maxLength": 1024,
            "minLength": 1,
            "title": "Sourcename",
            "type": "string"
          },
          "startInBlock": {
            "minimum": 0.0,
            "title": "Startinblock",
            "type": "integer"
          }
        },
        "required": [
          "blockId",
          "driveFileId",
          "endExclusiveInBlock",
          "exactQuote",
          "lineStartOneBased",
          "normalizedValue",
          "originKind",
          "pageIndexZeroBased",
          "path",
          "printedPageLabel",
          "rawValue",
          "role",
          "sourceName",
          "startInBlock"
        ],
        "title": "WorkspaceEvidencePassageView",
        "type": "object"
      },
      "WorkspaceFolderView": {
        "additionalProperties": false,
        "properties": {
          "driveFolderId": {
            "maxLength": 200,
            "minLength": 10,
            "title": "Drivefolderid",
            "type": "string"
          },
          "name": {
            "anyOf": [
              {
                "maxLength": 1024,
                "minLength": 1,
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "title": "Name"
          }
        },
        "required": [
          "driveFolderId",
          "name"
        ],
        "title": "WorkspaceFolderView",
        "type": "object"
      },
      "WorkspaceIngestionView": {
        "additionalProperties": false,
        "properties": {
          "cappedFiles": {
            "minimum": 0.0,
            "title": "Cappedfiles",
            "type": "integer"
          },
          "discoveredFiles": {
            "minimum": 0.0,
            "title": "Discoveredfiles",
            "type": "integer"
          },
          "discoveryComplete": {
            "title": "Discoverycomplete",
            "type": "boolean"
          },
          "errorCode": {
            "anyOf": [
              {
                "maxLength": 80,
                "minLength": 1,
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "title": "Errorcode"
          },
          "failedFiles": {
            "minimum": 0.0,
            "title": "Failedfiles",
            "type": "integer"
          },
          "finishedAt": {
            "anyOf": [
              {
                "format": "date-time",
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "title": "Finishedat"
          },
          "foldersVisited": {
            "minimum": 0.0,
            "title": "Foldersvisited",
            "type": "integer"
          },
          "gapReasons": {
            "items": {
              "enum": [
                "processing",
                "failed",
                "unsupported",
                "inaccessible",
                "capped",
                "unknown_branch",
                "unstable",
                "unsafe_to_parse"
              ],
              "type": "string"
            },
            "title": "Gapreasons",
            "type": "array"
          },
          "parsingFiles": {
            "minimum": 0.0,
            "title": "Parsingfiles",
            "type": "integer"
          },
          "queuedFiles": {
            "minimum": 0.0,
            "title": "Queuedfiles",
            "type": "integer"
          },
          "readyFiles": {
            "minimum": 0.0,
            "title": "Readyfiles",
            "type": "integer"
          },
          "runId": {
            "format": "uuid",
            "title": "Runid",
            "type": "string"
          },
          "startedAt": {
            "anyOf": [
              {
                "format": "date-time",
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "title": "Startedat"
          },
          "status": {
            "enum": [
              "enqueue_pending",
              "queued",
              "discovering",
              "processing",
              "ready",
              "partial",
              "failed",
              "retryable"
            ],
            "title": "Status",
            "type": "string"
          },
          "unsupportedFiles": {
            "minimum": 0.0,
            "title": "Unsupportedfiles",
            "type": "integer"
          }
        },
        "required": [
          "cappedFiles",
          "discoveryComplete",
          "discoveredFiles",
          "errorCode",
          "failedFiles",
          "finishedAt",
          "foldersVisited",
          "gapReasons",
          "parsingFiles",
          "queuedFiles",
          "readyFiles",
          "runId",
          "startedAt",
          "status",
          "unsupportedFiles"
        ],
        "title": "WorkspaceIngestionView",
        "type": "object"
      },
      "WorkspaceQuestionResultView": {
        "additionalProperties": false,
        "properties": {
          "answerId": {
            "format": "uuid",
            "title": "Answerid",
            "type": "string"
          },
          "claims": {
            "items": {
              "$ref": "#/components/schemas/WorkspaceApprovedClaimView"
            },
            "maxItems": 200,
            "title": "Claims",
            "type": "array"
          },
          "coverageGapReasons": {
            "items": {
              "enum": [
                "processing",
                "failed",
                "unsupported",
                "inaccessible",
                "capped",
                "unknown_branch",
                "unstable",
                "unsafe_to_parse"
              ],
              "type": "string"
            },
            "maxItems": 8,
            "title": "Coveragegapreasons",
            "type": "array"
          },
          "createdAt": {
            "format": "date-time",
            "title": "Createdat",
            "type": "string"
          },
          "generationStatus": {
            "enum": [
              "not_configured",
              "failed",
              "completed"
            ],
            "title": "Generationstatus",
            "type": "string"
          },
          "message": {
            "maxLength": 280,
            "minLength": 1,
            "title": "Message",
            "type": "string"
          },
          "passages": {
            "items": {
              "$ref": "#/components/schemas/WorkspaceEvidencePassageView"
            },
            "maxItems": 6,
            "title": "Passages",
            "type": "array"
          },
          "policyVersion": {
            "enum": [
              "retrieval-policy-v1",
              "publication-policy-v1",
              "clarification-policy-v1",
              "exhaustive-extraction-policy-v1",
              "exhaustive-premium-policy-v1",
              "source-state-policy-v1",
              "structured-analysis-policy-v1"
            ],
            "title": "Policyversion",
            "type": "string"
          },
          "question": {
            "maxLength": 2000,
            "minLength": 3,
            "title": "Question",
            "type": "string"
          },
          "questionId": {
            "format": "uuid",
            "title": "Questionid",
            "type": "string"
          },
          "status": {
            "enum": [
              "evidence_retrieved",
              "evidence_supported",
              "changed",
              "conflict",
              "insufficient",
              "coverage_limited"
            ],
            "title": "Status",
            "type": "string"
          }
        },
        "required": [
          "answerId",
          "claims",
          "coverageGapReasons",
          "createdAt",
          "generationStatus",
          "message",
          "passages",
          "policyVersion",
          "question",
          "questionId",
          "status"
        ],
        "title": "WorkspaceQuestionResultView",
        "type": "object"
      },
      "WorkspaceSource": {
        "additionalProperties": false,
        "properties": {
          "documentVersionId": {
            "format": "uuid",
            "title": "Documentversionid",
            "type": "string"
          },
          "evaluated": {
            "title": "Evaluated",
            "type": "boolean"
          },
          "fileName": {
            "maxLength": 240,
            "minLength": 1,
            "title": "Filename",
            "type": "string"
          },
          "observedAt": {
            "format": "date-time",
            "title": "Observedat",
            "type": "string"
          },
          "reason": {
            "anyOf": [
              {
                "maxLength": 120,
                "minLength": 1,
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "title": "Reason"
          },
          "selected": {
            "title": "Selected",
            "type": "boolean"
          },
          "status": {
            "enum": [
              "ready",
              "unsupported"
            ],
            "title": "Status",
            "type": "string"
          }
        },
        "required": [
          "documentVersionId",
          "evaluated",
          "fileName",
          "observedAt",
          "selected",
          "status"
        ],
        "title": "WorkspaceSource",
        "type": "object"
      },
      "WorkspaceSourceView": {
        "additionalProperties": false,
        "properties": {
          "blockCount": {
            "minimum": 0.0,
            "title": "Blockcount",
            "type": "integer"
          },
          "driveFileId": {
            "maxLength": 200,
            "minLength": 1,
            "title": "Drivefileid",
            "type": "string"
          },
          "errorCode": {
            "anyOf": [
              {
                "maxLength": 80,
                "minLength": 1,
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "title": "Errorcode"
          },
          "extractionMethod": {
            "anyOf": [
              {
                "enum": [
                  "embedded_text",
                  "ocr"
                ],
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "title": "Extractionmethod"
          },
          "mimeType": {
            "maxLength": 255,
            "minLength": 1,
            "title": "Mimetype",
            "type": "string"
          },
          "name": {
            "maxLength": 1024,
            "minLength": 1,
            "title": "Name",
            "type": "string"
          },
          "pageCount": {
            "anyOf": [
              {
                "minimum": 0.0,
                "type": "integer"
              },
              {
                "type": "null"
              }
            ],
            "title": "Pagecount"
          },
          "path": {
            "items": {
              "type": "string"
            },
            "maxItems": 8,
            "minItems": 2,
            "title": "Path",
            "type": "array"
          },
          "reasonCode": {
            "anyOf": [
              {
                "maxLength": 80,
                "minLength": 1,
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "title": "Reasoncode"
          },
          "sizeBytes": {
            "anyOf": [
              {
                "minimum": 0.0,
                "type": "integer"
              },
              {
                "type": "null"
              }
            ],
            "title": "Sizebytes"
          },
          "status": {
            "enum": [
              "queued",
              "parsing",
              "ready",
              "failed",
              "unsupported",
              "capped"
            ],
            "title": "Status",
            "type": "string"
          }
        },
        "required": [
          "blockCount",
          "driveFileId",
          "errorCode",
          "extractionMethod",
          "mimeType",
          "name",
          "path",
          "pageCount",
          "reasonCode",
          "sizeBytes",
          "status"
        ],
        "title": "WorkspaceSourceView",
        "type": "object"
      },
      "WorkspaceSummary": {
        "additionalProperties": false,
        "properties": {
          "name": {
            "maxLength": 160,
            "minLength": 1,
            "title": "Name",
            "type": "string"
          },
          "revisionLabel": {
            "anyOf": [
              {
                "maxLength": 80,
                "minLength": 1,
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "title": "Revisionlabel"
          },
          "sampleLabel": {
            "maxLength": 80,
            "minLength": 1,
            "title": "Samplelabel",
            "type": "string"
          },
          "sources": {
            "items": {
              "$ref": "#/components/schemas/WorkspaceSource"
            },
            "maxItems": 100,
            "title": "Sources",
            "type": "array"
          }
        },
        "required": [
          "name",
          "revisionLabel",
          "sampleLabel",
          "sources"
        ],
        "title": "WorkspaceSummary",
        "type": "object"
      },
      "WorkspaceView": {
        "additionalProperties": false,
        "properties": {
          "createdAt": {
            "format": "date-time",
            "title": "Createdat",
            "type": "string"
          },
          "folder": {
            "$ref": "#/components/schemas/WorkspaceFolderView"
          },
          "history": {
            "items": {
              "$ref": "#/components/schemas/WorkspaceQuestionResultView"
            },
            "maxItems": 20,
            "title": "History",
            "type": "array"
          },
          "ingestion": {
            "$ref": "#/components/schemas/WorkspaceIngestionView"
          },
          "sources": {
            "items": {
              "$ref": "#/components/schemas/WorkspaceSourceView"
            },
            "maxItems": 500,
            "title": "Sources",
            "type": "array"
          },
          "workspaceId": {
            "format": "uuid",
            "title": "Workspaceid",
            "type": "string"
          }
        },
        "required": [
          "createdAt",
          "folder",
          "history",
          "ingestion",
          "sources",
          "workspaceId"
        ],
        "title": "WorkspaceView",
        "type": "object"
      }
    }
  },
  "info": {
    "title": "Extent API",
    "version": "0.1.0"
  },
  "openapi": "3.1.0",
  "paths": {
    "/api/v1/auth/google/callback": {
      "get": {
        "operationId": "complete_google_authorization_api_v1_auth_google_callback_get",
        "parameters": [
          {
            "in": "query",
            "name": "code",
            "required": false,
            "schema": {
              "anyOf": [
                {
                  "maxLength": 4096,
                  "type": "string"
                },
                {
                  "type": "null"
                }
              ],
              "title": "Code"
            }
          },
          {
            "in": "query",
            "name": "state",
            "required": false,
            "schema": {
              "anyOf": [
                {
                  "maxLength": 256,
                  "type": "string"
                },
                {
                  "type": "null"
                }
              ],
              "title": "State"
            }
          },
          {
            "in": "query",
            "name": "error",
            "required": false,
            "schema": {
              "anyOf": [
                {
                  "maxLength": 200,
                  "type": "string"
                },
                {
                  "type": "null"
                }
              ],
              "title": "Error"
            }
          }
        ],
        "responses": {
          "303": {
            "description": "Return to the same-origin connect surface"
          },
          "307": {
            "description": "Successful Response"
          },
          "422": {
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HTTPValidationError"
                }
              }
            },
            "description": "Validation Error"
          }
        },
        "summary": "Complete Google Authorization",
        "tags": [
          "authentication"
        ]
      }
    },
    "/api/v1/auth/google/start": {
      "get": {
        "operationId": "start_google_authorization_api_v1_auth_google_start_get",
        "responses": {
          "307": {
            "description": "Redirect to Google's authorization endpoint"
          }
        },
        "summary": "Start Google Authorization",
        "tags": [
          "authentication"
        ]
      }
    },
    "/api/v1/auth/session": {
      "delete": {
        "operationId": "disconnect_session_api_v1_auth_session_delete",
        "responses": {
          "204": {
            "description": "Successful Response"
          },
          "403": {
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/AuthErrorView"
                }
              }
            },
            "description": "Origin check failed"
          }
        },
        "summary": "Disconnect Session",
        "tags": [
          "authentication"
        ]
      },
      "get": {
        "operationId": "read_session_api_v1_auth_session_get",
        "responses": {
          "200": {
            "content": {
              "application/json": {
                "schema": {
                  "anyOf": [
                    {
                      "$ref": "#/components/schemas/SignedOutSessionView"
                    },
                    {
                      "$ref": "#/components/schemas/AuthenticatedSessionView"
                    }
                  ],
                  "title": "Response Read Session Api V1 Auth Session Get"
                }
              }
            },
            "description": "Current opaque browser-session state"
          }
        },
        "summary": "Read Session",
        "tags": [
          "authentication"
        ]
      }
    },
    "/api/v1/demo/preview": {
      "get": {
        "operationId": "get_demo_preview",
        "responses": {
          "200": {
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/SampleWorkspaceProjection"
                }
              }
            },
            "description": "Successful Response"
          }
        },
        "summary": "Read the prepared Alder Peak landing-page sample",
        "tags": [
          "demo"
        ]
      }
    },
    "/api/v1/demo/questions": {
      "post": {
        "operationId": "ask_demo_question",
        "parameters": [
          {
            "in": "header",
            "name": "Idempotency-Key",
            "required": true,
            "schema": {
              "maxLength": 128,
              "minLength": 1,
              "title": "Idempotency-Key",
              "type": "string"
            }
          }
        ],
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "$ref": "#/components/schemas/AskWorkspaceQuestionRequest"
              }
            }
          },
          "required": true
        },
        "responses": {
          "201": {
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/WorkspaceQuestionResultView"
                }
              }
            },
            "description": "Successful Response"
          },
          "403": {
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/WorkspaceErrorView"
                }
              }
            },
            "description": "Forbidden"
          },
          "422": {
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HTTPValidationError"
                }
              }
            },
            "description": "Validation Error"
          },
          "429": {
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/WorkspaceErrorView"
                }
              }
            },
            "description": "Too Many Requests"
          },
          "503": {
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/WorkspaceErrorView"
                }
              }
            },
            "description": "Service Unavailable"
          }
        },
        "summary": "Ask an anonymous question about the prepared sample",
        "tags": [
          "demo"
        ]
      }
    },
    "/api/v1/demo/workspace": {
      "get": {
        "operationId": "get_demo_workspace",
        "parameters": [
          {
            "in": "header",
            "name": "if-none-match",
            "required": false,
            "schema": {
              "anyOf": [
                {
                  "type": "string"
                },
                {
                  "type": "null"
                }
              ],
              "title": "If-None-Match"
            }
          }
        ],
        "responses": {
          "200": {
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/SampleWorkspaceProjection"
                }
              }
            },
            "description": "Successful Response"
          },
          "422": {
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HTTPValidationError"
                }
              }
            },
            "description": "Validation Error"
          }
        },
        "summary": "Read the interactive Alder Peak sample workspace",
        "tags": [
          "demo"
        ]
      }
    },
    "/api/v1/health": {
      "get": {
        "operationId": "get_health",
        "responses": {
          "200": {
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HealthResponse"
                }
              }
            },
            "description": "Successful Response"
          }
        },
        "summary": "Check API liveness",
        "tags": [
          "operations"
        ]
      }
    },
    "/api/v1/workspaces": {
      "post": {
        "operationId": "create_workspace_api_v1_workspaces_post",
        "parameters": [
          {
            "in": "header",
            "name": "Idempotency-Key",
            "required": true,
            "schema": {
              "maxLength": 128,
              "minLength": 1,
              "title": "Idempotency-Key",
              "type": "string"
            }
          }
        ],
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "$ref": "#/components/schemas/CreateWorkspaceRequest"
              }
            }
          },
          "required": true
        },
        "responses": {
          "202": {
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/WorkspaceView"
                }
              }
            },
            "description": "Successful Response"
          },
          "401": {
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/WorkspaceErrorView"
                }
              }
            },
            "description": "Unauthorized"
          },
          "403": {
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/WorkspaceErrorView"
                }
              }
            },
            "description": "Forbidden"
          },
          "409": {
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/WorkspaceErrorView"
                }
              }
            },
            "description": "Conflict"
          },
          "422": {
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/WorkspaceErrorView"
                }
              }
            },
            "description": "Unprocessable Content"
          }
        },
        "summary": "Create Workspace",
        "tags": [
          "workspaces"
        ]
      }
    },
    "/api/v1/workspaces/{workspace_id}": {
      "get": {
        "operationId": "read_workspace_api_v1_workspaces__workspace_id__get",
        "parameters": [
          {
            "in": "path",
            "name": "workspace_id",
            "required": true,
            "schema": {
              "format": "uuid",
              "title": "Workspace Id",
              "type": "string"
            }
          }
        ],
        "responses": {
          "200": {
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/WorkspaceView"
                }
              }
            },
            "description": "Successful Response"
          },
          "401": {
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/WorkspaceErrorView"
                }
              }
            },
            "description": "Unauthorized"
          },
          "404": {
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/WorkspaceErrorView"
                }
              }
            },
            "description": "Not Found"
          },
          "422": {
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HTTPValidationError"
                }
              }
            },
            "description": "Validation Error"
          }
        },
        "summary": "Read Workspace",
        "tags": [
          "workspaces"
        ]
      }
    },
    "/api/v1/workspaces/{workspace_id}/messages": {
      "post": {
        "operationId": "ask_workspace_question_api_v1_workspaces__workspace_id__messages_post",
        "parameters": [
          {
            "in": "path",
            "name": "workspace_id",
            "required": true,
            "schema": {
              "format": "uuid",
              "title": "Workspace Id",
              "type": "string"
            }
          },
          {
            "in": "header",
            "name": "Idempotency-Key",
            "required": true,
            "schema": {
              "maxLength": 128,
              "minLength": 1,
              "title": "Idempotency-Key",
              "type": "string"
            }
          }
        ],
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "$ref": "#/components/schemas/AskWorkspaceQuestionRequest"
              }
            }
          },
          "required": true
        },
        "responses": {
          "201": {
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/WorkspaceQuestionResultView"
                }
              }
            },
            "description": "Successful Response"
          },
          "401": {
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/WorkspaceErrorView"
                }
              }
            },
            "description": "Unauthorized"
          },
          "403": {
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/WorkspaceErrorView"
                }
              }
            },
            "description": "Forbidden"
          },
          "404": {
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/WorkspaceErrorView"
                }
              }
            },
            "description": "Not Found"
          },
          "409": {
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/WorkspaceErrorView"
                }
              }
            },
            "description": "Conflict"
          },
          "422": {
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HTTPValidationError"
                }
              }
            },
            "description": "Validation Error"
          },
          "429": {
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/WorkspaceErrorView"
                }
              }
            },
            "description": "Too Many Requests"
          },
          "503": {
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/WorkspaceErrorView"
                }
              }
            },
            "description": "Service Unavailable"
          }
        },
        "summary": "Ask Workspace Question",
        "tags": [
          "workspaces"
        ]
      }
    },
    "/api/v1/workspaces/{workspace_id}/retry": {
      "post": {
        "operationId": "retry_workspace_api_v1_workspaces__workspace_id__retry_post",
        "parameters": [
          {
            "in": "path",
            "name": "workspace_id",
            "required": true,
            "schema": {
              "format": "uuid",
              "title": "Workspace Id",
              "type": "string"
            }
          }
        ],
        "responses": {
          "202": {
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/WorkspaceView"
                }
              }
            },
            "description": "Successful Response"
          },
          "401": {
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/WorkspaceErrorView"
                }
              }
            },
            "description": "Unauthorized"
          },
          "403": {
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/WorkspaceErrorView"
                }
              }
            },
            "description": "Forbidden"
          },
          "404": {
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/WorkspaceErrorView"
                }
              }
            },
            "description": "Not Found"
          },
          "409": {
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/WorkspaceErrorView"
                }
              }
            },
            "description": "Conflict"
          },
          "422": {
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HTTPValidationError"
                }
              }
            },
            "description": "Validation Error"
          }
        },
        "summary": "Retry Workspace",
        "tags": [
          "workspaces"
        ]
      }
    }
  }
} as const;
