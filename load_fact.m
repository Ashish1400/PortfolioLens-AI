// Create a TEXT Power Query parameter named ProjectFolder, pointing to the extracted project folder.
let
    Source = Csv.Document(
        File.Contents(ProjectFolder & "/artifacts/fact_loan_snapshot.csv"),
        [Delimiter=",", Encoding=65001, QuoteStyle=QuoteStyle.Csv]
    ),
    Headers = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),
    Types = Table.TransformColumnTypes(Headers, {
        {"loan_id", type text}, {"snapshot_month", type date},
        {"opening_balance", Currency.Type}, {"funding", Currency.Type},
        {"principal_paid", Currency.Type}, {"chargeoff", Currency.Type},
        {"ending_balance", Currency.Type}, {"days_past_due", Int64.Type},
        {"payment_ratio", type number}, {"utilization", type number},
        {"months_on_book", Int64.Type}, {"status", type text}, {"dpd_bucket", type text}
    }, "en-US")
in
    Types
