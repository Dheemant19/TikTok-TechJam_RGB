# Ways to Improve the KuaiRand Result

## The whole challenge in simple words

The organizer gives us records of videos that were shown to users. Our job is to build a model that gives every shown video a score. For each user, videos with higher scores are placed above videos with lower scores.

We are **not** searching the full TikTok video library. The organizer already gives us the candidate videos for each user. We only need to put those candidates in the best order.

The complete flow is:

1. Learn from the organizer's training data.
2. Check ideas on the validation data.
3. Keep the model that gets the best valid result.
4. Create a CSV file containing its scores.
5. Let the organizer score that file on the final hidden test.

## What the organizer provides

- **KuaiRand-Pure data:** Anonymous records from a short-video feed. The IDs do not tell us who a real person is.
- **Fixed data splits:** The organizer decides which dates are used for training, validation, and testing. We must not move rows between them.
- **The `long_view` answer:** This is `1` when the user watched the video long enough and `0` otherwise. It is the main answer our model learns to predict.
- **Extra behavior:** Fields such as click, like, follow, watch time, video duration, date, user ID, and video ID. These can help the model understand why a long view happened.
- **The official FM baseline:** A starter model that every improved model must beat.
- **The official evaluator:** `evaluate.py` calculates the scores. Its result is the source of truth.
- **The submission checker:** `submit.py` checks that our final CSV has the required columns and rows.

## What is inside the dataset

Each row means: **one video was shown to one user at one time**. The same user and video can appear more than once, so every row also has its own `row_id`.

Our prepared data has:

- **Training:** April 8–21, about **1.14 million rows**, **26,210 users**, and **7,538 videos**.
- **Validation:** April 22–28, **124,909 rows**, **22,377 users**, and **5,951 videos**.
- **Test:** April 29–May 8. We create scores for this later period, but do not use its hidden answers to choose a model.

About **33.7%** of training rows and **31.3%** of validation rows have `long_view = 1`. A training user has about **44 interactions on average**, although some users have far more.

The dates matter. We learn from earlier days and check on later days because real recommendation systems must predict future behavior, not memorize answers from the same day.

## What FM means

**FM means Factorization Machine.** It is the organizer's official baseline model.

The FM receives five main fields:

- user ID
- video ID
- author ID
- feed tab
- video-duration group

It learns small number lists for these IDs. These numbers act like hidden descriptions learned from behavior. The model then learns which pairs work well together, such as a user with a video or a user with an author.

For every row, the FM produces one score:

- Higher score means “this video should be ranked higher for this user.”
- Lower score means “this video should be ranked lower for this user.”

During training, the FM compares its score with the real `long_view` answer and adjusts its numbers when it is wrong. The official version uses a common yes-or-no training calculation called **binary cross-entropy**, or BCE.

The FM is a good simple model, but it does not naturally read a user's viewing history in order. That is why history models may have more room to improve.

## How the baseline is calculated

Training includes some randomness, so the same FM can produce slightly different results each time. We train the official FM five times with seeds 0, 1, 2, 3, and 4. A seed is simply a fixed starting number that makes one run repeatable.

The five validation results are averaged. The official reference is:

- **GAUC:** 0.6674
- **nDCG@5:** 0.5357
- **Primary score:** `(0.6674 + 0.5357) / 2 = 0.6016`

The organizer's test reference for the same FM is **0.5946**. Validation and test scores differ because they cover different dates and users. We use validation while developing; the final test is used only for the final result.

## What the two scores mean

- **GAUC:** Checks whether positive videos are usually placed above negative videos for the same user. It only uses users who have both kinds of videos.
- **nDCG@5:** Checks whether positive videos appear near the top, especially in the first five positions. Getting the first few positions right matters most.
- **Primary:** Gives GAUC and nDCG@5 equal importance by averaging them.

Some test users have no positive videos at all, so no model can give them a positive top-five result. Some users have only positive videos, so every order is already correct. The useful improvement comes mainly from users who have a mixture of positive and negative videos.

## What the final model produces

The final model creates one score for every test row. We save those scores in `predictions.csv` with four columns: `row_id`, `user_id`, `video_id`, and `score`.

Passing the CSV format check only means the file is shaped correctly. It does **not** mean the model won. The result is known only after the organizer uses the hidden answers to score the file.

## What our experiments are doing

Every experiment changes one part of the training pipeline, trains a real model, scores it with the official evaluator, and compares it with the FM baseline.

The recent experiments mostly kept the FM and changed its training calculation—for example, giving harder rows more importance, adding click or watch-time information, or weighting recent dates more heavily. Their scores stayed close to the baseline. This tells us that another small change to the same calculation is unlikely to be enough.

The next approaches below make larger but sensible changes: give the model better history information, train it to compare videos inside each user, or use a model that can understand more detailed patterns.

## What the latest run tells us

The official FM baseline scored **0.6016**. Our best experiments scored about **0.6014**, so they did not beat it.

Most experiments changed only the training loss while keeping the same FM model and almost the same input information. Their similar scores suggest that the loss is not the main problem. The next experiments should help the model understand each user's viewing history and compare videos more directly.

A convincing result should score at least **0.6036** on validation. That is the baseline plus the required improvement of **0.002**.

## Recommended approaches

- **Combine the five FM models**

  We already train the FM with five different random seeds. Each seed ranks some videos differently. For every user, we can average the five models' video ranks instead of choosing only one model. A quick validation check reached about **0.6028**. This is better than the baseline, but not yet enough. It is a useful starting point for the next experiments.

- **Create features from each user's past behavior**

  Give the model simple facts about what the user did before the current video appeared. Examples include the user's recent long-view rate, favorite creators or video groups, average watch completion, and time since watching a similar video. These features must use only earlier events so they do not leak future answers.

- **Train the model to rank a user's videos as a group**

  The score is based on the order of videos inside each user. Training should therefore show the model several candidates from the same user together. The model should learn to place positive videos above negative ones, with extra attention on the top five positions. This matches GAUC and nDCG@5 better than treating every row as an unrelated yes-or-no question.

- **Use a user-history model such as DIN**

  DIN looks through a user's earlier videos and chooses the parts of that history that matter for the current candidate. For example, when scoring a cooking video, it can focus on earlier cooking videos instead of using the user's whole history equally. This gives the model information that the current FM cannot represent.

- **Use separate outputs for click, long view, and watch time**

  Clicks and watch time can help predict `long_view`, but they do not mean exactly the same thing. The earlier experiments tried to make one score learn several meanings at once. A better model shares what it learns internally but has a separate output for each target. The final submission still uses only the `long_view` output.

- **Predict watch completion separately**

  Watching 20 seconds of a 20-second video is different from watching 20 seconds of a two-minute video. Train a separate output to predict the watched fraction or expected watch time. Its learned information can help the main `long_view` prediction without replacing it.

- **Try a stronger interaction model after adding history features**

  Models such as DeepFM or DCNv2 can learn more detailed combinations than the current FM. For example, they can connect a user's recent interest, a creator, and the time of day. This should come after better history features are available; simply making the current model larger has already shown little benefit.

- **Combine different successful models**

  If the FM, a grouped ranking model, and a history model make different mistakes, average their within-user ranks. Combining different models is usually more useful than combining several nearly identical models.

- **Use the randomized exposure log later**

  The normal feed data is affected by videos the old recommender chose to show. The randomized log can help reduce that bias. This is more difficult and should be attempted only after the simpler ranking and history models work reliably.

## Suggested experiment order

1. Properly test and log the five-seed FM rank average.
2. Add past-behavior features and train a user-grouped ranking model.
3. Add a DIN user-history model.
4. Add separate outputs for click and watch completion.
5. Combine the best different models.
6. Try randomized-log bias correction only if more improvement is needed.

## Approaches not worth repeating now

Do not spend more runs on focal loss, label smoothing, simple recency weights, a single calendar bias, or auxiliary labels attached to the same FM score. The latest session already showed that these small loss changes do not provide a meaningful gain.
