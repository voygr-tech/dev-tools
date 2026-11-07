# An AI agent that books a table by phone

Give [PlaceCall](https://github.com/voygr-tech/placecall) a restaurant's phone
number and your reservation details. Its hosted AI agent calls the restaurant
and asks for the booking. This Python example uses the
[VOYGR](https://voygr.tech) API; you do not need a separate model API key.

## Install

Clone [dev-tools](https://github.com/voygr-tech/dev-tools) and run this from its root:

```sh
python -m pip install -e .
```

Use Python 3.10 or newer. You can preview a request without an account.
To make a call, [get a free API key](https://api.voygr.tech/checkout) and set
`PLACECALL_API_KEY` in your environment. The script also accepts `VOYGR_API_KEY`
for the same account. The checkout page lists free credits and current rates.

## Preview a booking

The following command uses fictional phone numbers. Replace the restaurant,
numbers, reservation name and date/time with your own details before calling.
Include the UTC offset for the restaurant's local time on that date.

```sh
python -m examples.book_table.main \
  --phone +14155550100 --restaurant "Example Bistro" \
  --name "Jane Example" --party-size 2 \
  --at 2099-11-08T19:00:00-08:00 --callback +14155550101
```

The script prints the JSON request and exits without making a network request.
The brief asks for the exact date, time and party size, gives a callback number,
and asks the restaurant to read back the confirmed details. It declines payment
commitments and ends the call if a new decision is needed.

## Make the call

Review the preview. Use a number you are authorized to call and an account with
enough credits. Choose a unique idempotency key, such as a UUID, and keep it with
the request. Run the same command with these two options added:

```sh
  --confirm-call --idempotency-key YOUR_UNIQUE_CALL_KEY
```

This places a real outbound call. PlaceCall applies its destination policy and
opens with its default AI and recording notice. See the
[calling guide](https://api.voygr.tech/docs/guides/place-a-call/) for supported
destinations, billing and recording details.

The script submits once and prints the `call_id`. An accepted or queued call
does not mean the restaurant confirmed a reservation. Read the outcome with:

```sh
python -m examples.book_table.main --call-id CALL_ID
```

That command sends only a GET. It prints the structured result and transcript
fields returned by the API. If `status` is `completed` but `result` is `null`,
read the same call again after a few seconds. Use the outcome summary and
transcript to determine whether the restaurant confirmed your exact booking.
The [calling guide](https://api.voygr.tech/docs/guides/place-a-call/) explains
the result codes. For a complete transcript, check that `transcript_status`
is `final`, or that `recording_declined` is true and no transcript will arrive.

## Recover an uncertain submission

If the POST times out or returns an error, it may have placed the call. Within
24 hours, retry only with the same idempotency key and identical booking details.
The API replays the first call instead of dialing twice. After that window,
check your account's calls before deciding whether another call is needed.
If you have the `call_id`, use readback. Changing the key or the brief can create
a second real call.

## Use an assistant over MCP

Connect the maintained [PlaceCall MCP server](https://github.com/voygr-tech/placecall#install)
at `https://api.voygr.tech/mcp`. Ask your assistant to draft a booking request
with the restaurant phone, name, party size, local date/time and callback number.
Review the number and brief before authorizing it to call. The maintained
[agent instructions](https://github.com/voygr-tech/placecall/blob/main/AGENTS.md)
cover call results and mid-call questions; use that route when you want an
interactive agent.

Full [API documentation](https://api.voygr.tech/docs/).
