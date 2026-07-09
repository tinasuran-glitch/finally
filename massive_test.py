from massive import RESTClient

client = RESTClient("W7DzpSKFAQcc4Sp15khKw8ZbExv6_KRN")

details = client.get_ticker_details(
	"AAPL",
	)

print(details)