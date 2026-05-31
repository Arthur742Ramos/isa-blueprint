theory Sorting
  imports Main
begin

text \<open>
  Skeleton theory for the agent-workflow example. The blueprint tracks the
  proof obligations below; here we provide the base definitions that are
  marked `found`, leaving the lemmas/theorems as agent tasks.
\<close>

fun isort :: "'a::linorder list \<Rightarrow> 'a list" where
  "isort [] = []"
| "isort (x # xs) = insort x (isort xs)"

lemma rev_append: "rev (xs @ ys) = rev ys @ rev xs"
  by simp

theorem isort_sorted: "sorted (isort xs)"
  by (induct xs) (auto intro: sorted_insort)

end
