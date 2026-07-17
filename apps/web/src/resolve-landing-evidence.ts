interface ClaimWithCitations {
  readonly citationIds: readonly string[];
}

interface ItemWithCitationId {
  readonly citationId: string;
}

export const resolveLandingEvidence = <
  Claim extends ClaimWithCitations,
  Citation extends ItemWithCitationId,
  CitationContext extends ItemWithCitationId,
>(
  claims: readonly Claim[],
  citations: readonly Citation[],
  citationContexts: readonly CitationContext[],
): {
  readonly citation: Citation;
  readonly citationContext: CitationContext;
  readonly claim: Claim;
} => {
  const claim = claims[0];
  const citationId = claim?.citationIds[0];
  if (claim === undefined || citationId === undefined) {
    throw new Error("The public evidence preview was missing a claim citation.");
  }

  const citation = citations.find((candidate) => candidate.citationId === citationId);
  const citationContext = citationContexts.find(
    (candidate) => candidate.citationId === citationId,
  );
  if (citation === undefined || citationContext === undefined) {
    throw new Error("The public evidence preview citation could not be resolved.");
  }

  return { citation, citationContext, claim };
};
