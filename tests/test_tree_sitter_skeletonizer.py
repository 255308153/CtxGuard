"""Unit tests for TreeSitterSkeletonizer multi-language AST compression."""

import pytest
from ctxguard.core.compressors.ast_code import TreeSitterSkeletonizer


def test_treesitter_typescript_compression():
    ts_code = """
export async function fetchUserData(userId: string, options?: FetchOptions): Promise<UserRecord> {
    const endpoint = `/api/v1/users/${userId}`;
    const response = await fetch(endpoint, {
        headers: { "Authorization": "Bearer xxx" }
    });
    if (!response.ok) {
        throw new Error(`Failed to fetch user: ${response.statusText}`);
    }
    const data = await response.json();
    return transformUser(data);
}
"""
    skeleton = TreeSitterSkeletonizer.skeletonize(ts_code, lang_name="typescript", short_sha="sha_ts123", min_body_lines=3)
    assert skeleton is not None
    assert "export async function fetchUserData(userId: string, options?: FetchOptions): Promise<UserRecord>" in skeleton
    assert "Implementation folded" in skeleton
    assert "Use ctx_expand('sha_ts123')" in skeleton
    assert "const endpoint" not in skeleton


def test_treesitter_rust_compression():
    rust_code = """
pub fn process_stream(data: &[u8], config: &StreamConfig) -> Result<Summary, AppError> {
    let mut reader = BufReader::new(data);
    let mut total_bytes = 0;
    for line in reader.lines() {
        let l = line.map_err(|e| AppError::Io(e))?;
        total_bytes += l.len();
    }
    Ok(Summary { total_bytes })
}
"""
    skeleton = TreeSitterSkeletonizer.skeletonize(rust_code, lang_name="rust", short_sha="sha_rs123", min_body_lines=3)
    assert skeleton is not None
    assert "pub fn process_stream(data: &[u8], config: &StreamConfig) -> Result<Summary, AppError>" in skeleton
    assert "Implementation folded" in skeleton
    assert "Use ctx_expand('sha_rs123')" in skeleton
    assert "BufReader::new" not in skeleton


def test_treesitter_go_compression():
    go_code = """
func ProcessTransaction(ctx context.Context, tx *Transaction) (*Receipt, error) {
    if tx == nil {
        return nil, errors.New("transaction is nil")
    }
    if err := tx.Validate(); err != nil {
        return nil, fmt.Errorf("invalid transaction: %w", err)
    }
    receipt, err := executeTx(ctx, tx)
    if err != nil {
        return nil, err
    }
    return receipt, nil
}
"""
    skeleton = TreeSitterSkeletonizer.skeletonize(go_code, lang_name="go", short_sha="sha_go123", min_body_lines=3)
    assert skeleton is not None
    assert "func ProcessTransaction(ctx context.Context, tx *Transaction) (*Receipt, error)" in skeleton
    assert "Implementation folded" in skeleton
    assert "Use ctx_expand('sha_go123')" in skeleton
    assert "executeTx(ctx, tx)" not in skeleton


def test_treesitter_java_compression():
    java_code = """
public class PaymentGateway {
    public PaymentResult executePayment(PaymentRequest request) throws PaymentException {
        validateRequest(request);
        HttpHeaders headers = new HttpHeaders();
        headers.set("X-Merchant-ID", this.merchantId);
        HttpEntity<PaymentRequest> entity = new HttpEntity<>(request, headers);
        ResponseEntity<PaymentResult> response = restTemplate.postForEntity(url, entity, PaymentResult.class);
        return response.getBody();
    }
}
"""
    skeleton = TreeSitterSkeletonizer.skeletonize(java_code, lang_name="java", short_sha="sha_java123", min_body_lines=3)
    assert skeleton is not None
    assert "public PaymentResult executePayment(PaymentRequest request) throws PaymentException" in skeleton
    assert "Implementation folded" in skeleton
    assert "restTemplate.postForEntity" not in skeleton
