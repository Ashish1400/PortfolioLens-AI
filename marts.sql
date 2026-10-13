-- Source tables are validated, typed CSV data loaded by pipeline.py.
CREATE VIEW loan_panel AS
SELECT f.*, d.product, d.region, d.risk_band, d.origination_month,
       d.debt_to_income, d.original_principal, d.term_months, d.cohort
FROM fact_loan_snapshot f JOIN dim_loan d USING (loan_id);

CREATE VIEW mart_monthly AS
SELECT snapshot_month, COUNT(*) AS observed_loans,
       SUM(CASE WHEN ending_balance > 0 THEN 1 ELSE 0 END) AS active_loans,
       SUM(ending_balance) AS ending_balance,
       SUM(CASE WHEN days_past_due >= 30 THEN ending_balance ELSE 0 END) AS dpd30_balance,
       SUM(CASE WHEN days_past_due >= 60 THEN ending_balance ELSE 0 END) AS dpd60_balance,
       SUM(chargeoff) AS chargeoff_amount,
       SUM(funding) AS funding_amount,
       SUM(principal_paid) AS principal_paid,
       SUM(opening_balance) AS opening_balance,
       SUM(CASE WHEN days_past_due >= 30 THEN ending_balance ELSE 0 END)
         / NULLIF(SUM(ending_balance),0) AS dpd30_rate,
       SUM(CASE WHEN days_past_due >= 60 THEN ending_balance ELSE 0 END)
         / NULLIF(SUM(ending_balance),0) AS dpd60_rate,
       SUM(chargeoff) / NULLIF(SUM(opening_balance),0) AS monthly_chargeoff_rate
FROM loan_panel GROUP BY snapshot_month;

CREATE VIEW mart_segment AS
SELECT snapshot_month, region, product, risk_band,
       COUNT(*) AS observed_loans, SUM(ending_balance) AS ending_balance,
       SUM(CASE WHEN days_past_due >= 30 THEN ending_balance ELSE 0 END) AS dpd30_balance,
       SUM(CASE WHEN days_past_due >= 30 THEN ending_balance ELSE 0 END)
         / NULLIF(SUM(ending_balance),0) AS dpd30_rate
FROM loan_panel GROUP BY snapshot_month, region, product, risk_band;

CREATE VIEW mart_vintage AS
SELECT origination_month, months_on_book, SUM(ending_balance) AS ending_balance,
       SUM(CASE WHEN days_past_due >= 30 THEN ending_balance ELSE 0 END)
         / NULLIF(SUM(ending_balance),0) AS dpd30_rate
FROM loan_panel GROUP BY origination_month, months_on_book;

CREATE VIEW mart_roll_rates AS
WITH transitions AS (
  SELECT loan_id, snapshot_month, ending_balance, dpd_bucket,
    LEAD(snapshot_month) OVER (PARTITION BY loan_id ORDER BY snapshot_month) AS next_month,
    LEAD(dpd_bucket) OVER (PARTITION BY loan_id ORDER BY snapshot_month) AS next_bucket
  FROM fact_loan_snapshot
), counts AS (
 SELECT snapshot_month, dpd_bucket AS from_bucket, next_bucket AS to_bucket,
        COUNT(*) AS loans, SUM(ending_balance) AS starting_balance
 FROM transitions
 WHERE ending_balance > 0 AND next_month = DATE(snapshot_month, '+1 month')
 GROUP BY snapshot_month, dpd_bucket, next_bucket
)
SELECT *, 1.0 * loans / SUM(loans) OVER (PARTITION BY snapshot_month, from_bucket) AS count_roll_rate
FROM counts;
