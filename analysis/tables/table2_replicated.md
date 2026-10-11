# Table II (replicated from per_attempt.parquet, no defense, gpt-4.1)

| attack       | banking   | slack   | travel   | workspace   | Avg   |
|:-------------|:----------|:--------|:---------|:------------|:------|
| ignorprev    | 8.3%      | 3.8%    | 0.0%     | 0.0%        | 3.0%  |
| chatinject   | 28.5%     | 40.0%   | 2.1%     | 7.5%        | 19.5% |
| agentvigil   | 34.5%     | 85.5%   | 31.8%    | 43.3%       | 48.8% |
| cobra_full   | 47.9%     | 69.6%   | 37.4%    | 65.8%       | 55.2% |
| cobra_ablate | 23.1%     | 38.8%   | 18.5%    | 14.4%       | 23.7% |

## n per cell

| attack       |   banking |   slack |   travel |   workspace |
|:-------------|----------:|--------:|---------:|------------:|
| ignorprev    |       144 |     105 |      140 |         240 |
| chatinject   |       144 |     105 |      140 |         240 |
| agentvigil   |       110 |      83 |      107 |         187 |
| cobra_full   |       516 |     270 |      604 |         602 |
| cobra_ablate |       640 |     363 |     1065 |        1049 |