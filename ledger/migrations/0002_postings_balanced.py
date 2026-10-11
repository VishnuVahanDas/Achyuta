from django.db import migrations

# Integrity rule 1: a confirmed transaction must hold two or more postings that sum
# to zero. Enforced by deferred constraint triggers, so the check runs at commit,
# after the transaction and all of its postings have been written.
FORWARD = """
CREATE FUNCTION ledger_check_postings_balanced() RETURNS trigger AS $$
DECLARE
    ids bigint[];
    bad bigint;
BEGIN
    IF TG_TABLE_NAME = 'ledger_transaction' THEN
        ids := ARRAY[NEW.id];
    ELSIF TG_OP = 'INSERT' THEN
        ids := ARRAY[NEW.transaction_id];
    ELSIF TG_OP = 'DELETE' THEN
        ids := ARRAY[OLD.transaction_id];
    ELSE
        ids := ARRAY[OLD.transaction_id, NEW.transaction_id];
    END IF;

    SELECT t.id INTO bad
    FROM ledger_transaction t
    WHERE t.id = ANY(ids)
      AND t.status = 'confirmed'
      AND (
        (SELECT COALESCE(SUM(p.amount), 0) FROM ledger_posting p WHERE p.transaction_id = t.id) <> 0
        OR (SELECT COUNT(*) FROM ledger_posting p WHERE p.transaction_id = t.id) < 2
      )
    LIMIT 1;

    IF FOUND THEN
        RAISE EXCEPTION
            'Confirmed transaction % needs two or more postings that sum to zero', bad
            USING ERRCODE = 'check_violation',
                  CONSTRAINT = 'ledger_transaction_postings_balanced';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER ledger_transaction_postings_balanced
    AFTER INSERT OR UPDATE ON ledger_transaction
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION ledger_check_postings_balanced();

CREATE CONSTRAINT TRIGGER ledger_posting_postings_balanced
    AFTER INSERT OR UPDATE OR DELETE ON ledger_posting
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION ledger_check_postings_balanced();
"""

REVERSE = """
DROP TRIGGER ledger_posting_postings_balanced ON ledger_posting;
DROP TRIGGER ledger_transaction_postings_balanced ON ledger_transaction;
DROP FUNCTION ledger_check_postings_balanced();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("ledger", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(FORWARD, REVERSE),
    ]
