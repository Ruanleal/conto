package com.conto.notificacoes;

import android.content.Context;
import android.content.SharedPreferences;

import org.json.JSONArray;

/** Onde o serviço guarda as notificações até o app tratá-las (SharedPreferences, em JSON). As regras ficam em Regras. */
final class Armazem {

  static final String ARQUIVO = "conto_notificacoes";
  static final String CHAVE_PENDENTES = "pendentes";
  static final String CHAVE_VISTOS = "vistos";
  static final String CHAVE_APPS = "apps";
  static final String CHAVE_SO_VALOR = "so_com_valor";
  static final String CHAVE_IGNORADOS = "ignorados";
  // diagnostico: o que o servico viu por ultimo (para a pessoa saber se o Android esta entregando as notificacoes)
  static final String CHAVE_CONECTADO = "conectado";
  static final String CHAVE_VISTAS = "diag_vistas";
  static final String CHAVE_ULT_APP = "diag_app";
  static final String CHAVE_ULT_MOTIVO = "diag_motivo";
  static final String CHAVE_ULT_QUANDO = "diag_quando";
  /** Vazio = todos os apps. Os pacotes dos bancos variam; filtrar pelo valor (R$) é mais seguro. */
  static final String APPS_PADRAO = "";

  static volatile LeitorNotificacoes componenteAtivo;

  private Armazem() {
  }

  static SharedPreferences prefs(Context c) {
    return c.getApplicationContext().getSharedPreferences(ARQUIVO, Context.MODE_PRIVATE);
  }

  static String monitorados(Context c) {
    return prefs(c).getString(CHAVE_APPS, APPS_PADRAO);
  }

  static String ignorados(Context c) {
    return prefs(c).getString(CHAVE_IGNORADOS, Regras.IGNORADOS_PADRAO);
  }

  static boolean soComValor(Context c) {
    return prefs(c).getBoolean(CHAVE_SO_VALOR, true);
  }

  private static JSONArray lerLista(Context c, String chave) {
    try {
      return new JSONArray(prefs(c).getString(chave, "[]"));
    } catch (Exception e) {
      return new JSONArray();
    }
  }

  static synchronized JSONArray ler(Context c) {
    return lerLista(c, CHAVE_PENDENTES);
  }

  /** Guarda se for nova e devolve {motivo, id} (id null quando nao guardou). */
  static synchronized String[] guardar(Context c, String app, String titulo, String texto, long quando) {
    try {
      JSONArray arr = ler(c);
      JSONArray vistos = lerLista(c, CHAVE_VISTOS);
      String[] r = Regras.guardarSeNova(arr, vistos, app, titulo, texto, quando);
      if (r[1] != null) {
        prefs(c).edit().putString(CHAVE_PENDENTES, arr.toString()).putString(CHAVE_VISTOS, vistos.toString()).commit();
      }
      return r;
    } catch (Exception e) {
      return new String[] {"erro ao guardar", null};
    }
  }

  static synchronized void remover(Context c, String id) {
    prefs(c).edit().putString(CHAVE_PENDENTES, Regras.semId(ler(c), id).toString()).commit();
  }

  static synchronized void limpar(Context c) {
    prefs(c).edit().putString(CHAVE_PENDENTES, "[]").commit();
  }

  /** Conta mais uma notificacao vista pelo servico e lembra a ultima (app, motivo, horario). */
  static synchronized void anotar(Context c, String app, String motivo, long quando) {
    SharedPreferences p = prefs(c);
    p.edit().putLong(CHAVE_VISTAS, p.getLong(CHAVE_VISTAS, 0) + 1).putString(CHAVE_ULT_APP, app == null ? "" : app)
        .putString(CHAVE_ULT_MOTIVO, motivo).putLong(CHAVE_ULT_QUANDO, quando).apply();
  }

  static void conectado(Context c, boolean sim) {
    prefs(c).edit().putBoolean(CHAVE_CONECTADO, sim).apply();
  }

  static String nomeConhecido(String p) {
    if (p == null) {
      return "";
    }
    String[][] nomes = {
        {"com.nu.production", "Nubank"}, {"com.itau", "Itaú"}, {"br.com.itau", "Itaú"}, {"com.bradesco", "Bradesco"},
        {"br.com.bb.android", "Banco do Brasil"}, {"br.com.gabba.Caixa", "Caixa"}, {"br.gov.caixa.tem", "Caixa Tem"},
        {"com.santander.app", "Santander"}, {"br.com.intermedium", "Inter"}, {"com.c6bank.app", "C6 Bank"},
        {"com.picpay", "PicPay"}, {"com.mercadopago.wallet", "Mercado Pago"}, {"br.com.uol.ps.myaccount", "PagBank"}
    };
    for (String[] n : nomes) {
      if (n[0].equals(p)) {
        return n[1];
      }
    }
    return p;
  }
}
