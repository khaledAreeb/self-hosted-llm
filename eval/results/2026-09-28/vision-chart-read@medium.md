# vision-chart-read@medium (vision)

| metric | value |
|---|---|
| prompt_tokens | 1148 |
| completion_tokens | 427 |
| reasoning_tokens | 308 |
| ttft_s | 1.25 |
| total_s | 5.09 |
| finish_reason | stop |
| answer_words | 70 |
| empty_answer | False |
| truncated | False |

attach: `eval/images/ontime-chart-2025.png`  max_tokens: 10000

## Prompt

Read this chart. Which month had the lowest on-time rate, and approximately what was it? Which months were below the target line? Summarise the trend in two sentences.

## Good answer looks like (written before running)

- **August, about 78%** (±2).
- Below target: **July (~88), August (~78), September (~86), October (~87)**. Exactly four months.
- Trend: steady above target January–June (91–94); a dip July–October bottoming in August; recovery in November–December (92–94).
- The bars carry no value labels, so values must be read from the gridlines, which are every 5 points.

## Answer

**Lowest month:** August, at roughly **78%** on-time delivery.

**Months below the 90% target line:** July (~88%), August (~78%), September (~86%), and October (~87%).

**Trend summary:** The year opened strongly, with January through June all meeting or exceeding the 90% target, but performance slipped in the summer, bottoming out in August before gradually climbing back. By November and December the rate had recovered to around 92–94%, returning above the target line.

## Reasoning

The user wants me to read a bar chart and answer three specific things: (1) the lowest month and its approximate value, (2) which months fell below the 90% target line, and (3) a two-sentence trend summary.

Let me extract values from the chart carefully. The y-axis runs 70–100 with gridlines every 5. The target line is at 90 (red dashed).

Reading each bar:
- Jan: ~93
- Feb: ~94
- Mar: ~92
- Apr: ~91
- May: ~93
- Jun: ~92
- Jul: ~88
- Aug: ~78
- Sep: ~86
- Oct: ~87
- Nov: ~92
- Dec: ~94

Lowest is August at about 78%.

Below the 90% target line: Jul (~88), Aug (~78), Sep (~86), Oct (~87). All others are at or above 90. Let me double check Apr at ~91, above. Yes.

Trend summary in two sentences: Strong start above target through June, then a dip in summer (Jul–Oct) with August as the trough, then recovery to target by Nov–Dec.

I'll write a clean, self-contained answer. No need for the user to see my reasoning.
