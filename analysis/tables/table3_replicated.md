# Table III (replicated, suite-averaged ASR per (attack, defense))

## ASR

| attack        | none   | transformers_pi_detector   | repeat_user_prompt   | spotlighting_with_delimiting   |
|:--------------|:-------|:---------------------------|:---------------------|:-------------------------------|
| ignorprev     | 3.0%   | 6.0%                       | 1.8%                 | 1.8%                           |
| topicattack   | —      | 3.5%                       | 0.5%                 | 5.2%                           |
| chatinject    | 19.5%  | 1.4%                       | 3.3%                 | 17.6%                          |
| agentvigil    | 48.8%  | —                          | —                    | —                              |
| cobra_full    | 52.2%  | —                          | 28.6%                | 62.8%                          |
| asr_knowledge | —      | —                          | 6.7%                 | —                              |
| cobra_ablate  | 23.4%  | —                          | —                    | —                              |

## Utility

| attack        | none   | transformers_pi_detector   | repeat_user_prompt   | spotlighting_with_delimiting   |
|:--------------|:-------|:---------------------------|:---------------------|:-------------------------------|
| ignorprev     | 73.3%  | 28.1%                      | 77.8%                | 74.0%                          |
| topicattack   | —      | 32.7%                      | 78.9%                | 72.3%                          |
| chatinject    | 71.5%  | 31.7%                      | 78.7%                | 72.5%                          |
| agentvigil    | —      | —                          | —                    | —                              |
| cobra_full    | 30.2%  | —                          | 58.1%                | 27.2%                          |
| asr_knowledge | —      | —                          | 73.8%                | —                              |
| cobra_ablate  | 55.0%  | —                          | —                    | —                              |

## n per cell

| attack        | none   | transformers_pi_detector   | repeat_user_prompt   | spotlighting_with_delimiting   |
|:--------------|:-------|:---------------------------|:---------------------|:-------------------------------|
| ignorprev     | 629    | 1258                       | 629                  | 629                            |
| topicattack   | —      | 563                        | 644                  | 649                            |
| chatinject    | 629    | 629                        | 629                  | 629                            |
| agentvigil    | 487    | —                          | —                    | —                              |
| cobra_full    | 3779   | —                          | 1196                 | 950                            |
| asr_knowledge | —      | —                          | 1894                 | —                              |
| cobra_ablate  | 3586   | —                          | —                    | —                              |