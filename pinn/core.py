"""Network, derivatives and the Adam + L-BFGS training loop shared by all the PINN cases."""

import time

import torch
from torch import nn


class Mlp(nn.Module):
    """Fully connected tanh network with Glorot weights and zero biases."""

    def __init__(self, n_in, n_out, width, depth):
        super().__init__()
        mods, w = [], n_in
        for _ in range(depth):
            mods += [nn.Linear(w, width), nn.Tanh()]
            w = width
        mods.append(nn.Linear(w, n_out))
        self.net = nn.Sequential(*mods)
        for m in self.net:
            if isinstance(m, nn.Linear):
                nn.init.xavier_uniform_(m.weight)
                nn.init.zeros_(m.bias)

    def forward(self, x):
        return self.net(x)


def ddx(y, x):
    """dy/dx by automatic differentiation, keeping the graph for the loss gradient (y and x are columns)."""
    return torch.autograd.grad(y, x, torch.ones_like(y), create_graph=True)[0]


def fit(params, loss_terms, adam=20000, lr=1e-3, lbfgs=5000, log_every=1000, verbose=False, history_size=50):
    """Minimise sum(loss_terms()), Adam first and then L-BFGS. loss_terms returns {name: scalar tensor}.
    Stops early on a non-finite loss. Returns the history as a list of {step, stage, seconds, total, <terms>}."""
    params = list(params)
    hist, t0 = [], time.time()

    def record(step, stage, terms):
        vals = {k: v.item() for k, v in terms.items()}
        row = {"step": step, "stage": stage, "seconds": time.time() - t0, **vals, "total": sum(vals.values())}
        hist.append(row)
        if verbose:
            print(f"{stage} {step:6d} total {row['total']:.3e} " + " ".join(f"{k} {v:.2e}" for k, v in vals.items()),
                  flush=True)
        return row["total"]

    opt = torch.optim.Adam(params, lr=lr)
    for step in range(adam):
        opt.zero_grad()
        terms = loss_terms()
        loss = sum(terms.values())
        if not torch.isfinite(loss):
            record(step, "adam", terms)
            return hist
        loss.backward()
        opt.step()
        if step % log_every == 0 or step == adam - 1:
            record(step, "adam", terms)
    if lbfgs:
        opt = torch.optim.LBFGS(params, lr=1.0, max_iter=lbfgs, max_eval=int(1.25 * lbfgs), history_size=history_size,
                                tolerance_grad=1e-12, tolerance_change=1e-14, line_search_fn="strong_wolfe")
        count = [0]

        def closure():
            opt.zero_grad()
            terms = loss_terms()
            loss = sum(terms.values())
            if loss.requires_grad:
                loss.backward()
            count[0] += 1
            if count[0] % log_every == 0:
                record(adam + count[0], "lbfgs", terms)
            return loss

        opt.step(closure)
        record(adam + count[0], "lbfgs", loss_terms())
    return hist


def seed_all(seed):
    torch.manual_seed(seed)
