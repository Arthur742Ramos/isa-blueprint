theory Relations
  imports Main
begin

text \<open>
  Skeleton theory for the LaTeX blueprint example. The facts referenced by
  blueprint.tex (relation_def, reflexive_def, eq_equivalence, ...) would be
  developed here. Stubs use `sorry` so the example stays lightweight.
\<close>

definition reflexive :: "('a \<times> 'a) set \<Rightarrow> bool" where
  "reflexive R \<longleftrightarrow> (\<forall>a. (a, a) \<in> R)"

definition symmetric :: "('a \<times> 'a) set \<Rightarrow> bool" where
  "symmetric R \<longleftrightarrow> (\<forall>a b. (a, b) \<in> R \<longrightarrow> (b, a) \<in> R)"

definition transitive :: "('a \<times> 'a) set \<Rightarrow> bool" where
  "transitive R \<longleftrightarrow> (\<forall>a b c. (a, b) \<in> R \<and> (b, c) \<in> R \<longrightarrow> (a, c) \<in> R)"

lemma eq_equivalence: "reflexive Id \<and> symmetric Id \<and> transitive Id"
  by (auto simp: reflexive_def symmetric_def transitive_def)

end
