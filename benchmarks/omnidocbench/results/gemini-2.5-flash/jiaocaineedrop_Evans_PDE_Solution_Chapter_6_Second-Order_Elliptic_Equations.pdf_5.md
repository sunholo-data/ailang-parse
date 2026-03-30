[
  {
    "type": "text",
    "text": "10. Proof. We omit (a) since is standard. For (b), if u attains an interior maximum, then the conclusion follows from strong maximum principle."
  },
  {
    "type": "text",
    "text": "If not, then for some $x^0 \\in \\partial U, u(x^0) > u(x) \\forall x \\in U$. Then Hopf's lemma implies $\\frac{\\partial u}{\\partial \\nu}(x^0) > 0$, which is a contradiction."
  },
  {
    "type": "text",
    "text": "Remark 2. A generalization of this problem to mixed boundary conditions is recorded in Gilbarg-Trudinger, Elliptic PDEs of second order, Problem 3.1."
  },
  {
    "type": "text",
    "text": "11. Proof. Define"
  },
  {
    "type": "text",
    "text": "$B[u, v] = \\int_U \\sum_{i,j} a^{ij} u_{x_i} v_{x_j} dx$ for $u \\in H^1(U), v \\in H_0^1(U)$."
  },
  {
    "type": "text",
    "text": "By Exercise 5.17, $\\phi(u) \\in H^1(U)$. Then, for all $v\\in C_c^\\infty(U), v \\ge 0$,"
  },
  {
    "type": "text",
    "text": "$B[\\phi(u), v]\n= \\int_U \\sum_{i,j} a^{ij} (\\phi(u))_{x_i} v_{x_j} dx\n= \\int_U \\sum_{i,j} a^{ij} \\phi'(u) u_{x_i} v_{x_j} dx \\text{, } (\\phi'(u) \\text{ is bounded since u is bounded})\n= \\int_U \\sum_{i,j} a^{ij} u_{x_i} (\\phi'(u)v)_{x_j} - \\sum_{i,j} a^{ij} \\phi''(u) u_{x_i} u_{x_j} v dx\n\\le 0 - \\int_U \\phi''(u) v |Du|^2 dx \\le 0 \\text{, by convexity of } \\phi$."
  },
  {
    "type": "text",
    "text": "(We don't know whether the product of two $H^1$ functions is weakly differentiable. This is why we do not take $v \\in H_0^1$.) Now we complete the proof with the standard density argument."
  },
  {
    "type": "text",
    "text": "12. Proof. Given $u \\in C^2(\\bar{U}) \\cap C(\\bar{U})$ with $Lu \\le 0$ in $U$ and $u \\le 0$ on $\\partial U$. Since $\\bar{U}$ is compact and $v \\in C(\\bar{U}), v \\ge c > 0$. So $w := \\frac{u}{v} \\in C^2(U) \\cap C(\\bar{U})$. Brutal computation gives us"
  },
  {
    "type": "text",
    "text": "$-a^{ij} w_{x_i x_j} = \\frac{-a^{ij} u_{x_i x_j} v + a^{ij} v_{x_i x_j} u}{v^2} + \\frac{a^{ij} v_{x_i} u_{x_j} - a^{ij} u_{x_i} v_{x_j}}{v^2} - a^{ij} \\frac{v_{x_i} v_{x_j} u - v u_{x_i}}{v^2}\n= \\frac{(Lu - b^i u_{x_i} - cu)v + (-Lv + b^i v_{x_i} + cv)u}{v^2} + 0 + a^{ij} \\frac{v_{x_i} v_{x_j}}{v^2} u \\text{, since } a^{ij} = a^{ji}.\n= \\frac{Lu}{v} - \\frac{uLv}{v^2} - b^i w_{x_i} + a^{ij} \\frac{v_{x_j}}{v} w_{x_i}$"
  },
  {
    "type": "text",
    "text": "Therefore,"
  },
  {
    "type": "text",
    "text": "$Mw := -a^{ij} w_{x_i x_j} + w_{x_i} [b^i - a^{ij} \\frac{2}{v} v_{x_j}] = \\frac{Lu}{v} - \\frac{uLv}{v^2} \\le 0 \\text{ on } \\{x \\in \\bar{U} : u > 0\\} \\subseteq U$."
  },
  {
    "type": "text",
    "text": "If $\{x \\in \\bar{U} : u > 0\}$ is not empty, Weak maximum principle to the operator M with bounded coefficients (since $v \\in C^1(\\bar{U})$) will lead a contradiction that"
  },
  {
    "type": "text",
    "text": "$0 < \\max_{\\{u>0\\}} w = \\max_{\\partial\\{u>0\\}} w = \\frac{0}{v} = 0$."
  },
  {
    "type": "text",
    "text": "Hence $u \\le 0$ in $U$."
  }
]