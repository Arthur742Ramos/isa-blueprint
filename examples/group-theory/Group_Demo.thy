theory Group_Demo
  imports Main
begin

text \<open>
  A small stub theory whose fact names line up with the IDs referenced in
  @{file "blueprint.md"}. The statements here are illustrative placeholders
  so the blueprint has something to point at; a real project would carry
  the genuine definitions and proofs.
\<close>

locale group_demo =
  fixes prod :: "'a \<Rightarrow> 'a \<Rightarrow> 'a" (infixl "\<cdot>" 70)
    and one :: 'a ("e")
    and inv :: "'a \<Rightarrow> 'a"
  assumes assoc: "(a \<cdot> b) \<cdot> c = a \<cdot> (b \<cdot> c)"
    and left_id: "e \<cdot> a = a"
    and left_inv: "inv a \<cdot> a = e"
begin

lemma left_cancel: "a \<cdot> b = a \<cdot> c \<Longrightarrow> b = c"
  by (metis assoc left_id left_inv)

end

end
